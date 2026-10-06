# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import io
import unittest
from unittest.mock import MagicMock, patch
import httplib2
from googleapiclient.errors import HttpError
import google_drive_ocr as ocr


def http_error(status, reason='backendError'):
    return HttpError(httplib2.Response({'status': str(status)}),
                     ('{"error":{"errors":[{"reason":"' + reason + '"}]}}').encode())


class RetryTest(unittest.TestCase):
    @patch.object(ocr.time, 'sleep')
    def test_upload_connection_reset_reuses_request(self, sleep):
        service = MagicMock()
        service.files().create().execute.side_effect = [OSError(10054, 'reset'), {'id': 'known-file'}]
        downloader = MagicMock()
        downloader.next_chunk.return_value = (None, True)
        with patch.object(ocr, 'MediaIoBaseDownload', return_value=downloader):
            ocr.ocr_single_media_gdrive(object(), 'letter.jpeg', 'image/jpeg', service,
                                       export_only=True, log_func=lambda _: None)
        self.assertEqual(service.files().create().execute.call_count, 2)
        self.assertEqual(service.files().delete().execute.call_count, 1)

    @patch.object(ocr.time, 'sleep')
    def test_connection_reset_then_success(self, sleep):
        action = MagicMock(side_effect=[OSError(10054, 'connection reset'), 'ok'])
        logs, metrics = [], {}
        self.assertEqual(ocr.network_retry(action, label='image', log_func=logs.append, metrics=metrics), 'ok')
        self.assertEqual(action.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(metrics['network_retries'], 1)
        self.assertIn('2/4', logs[0])

    @patch.object(ocr.time, 'sleep')
    def test_temporary_server_error_exhausts_four_attempts(self, sleep):
        action = MagicMock(side_effect=http_error(503))
        with self.assertRaises(HttpError):
            ocr.network_retry(action, label='image', log_func=lambda _: None)
        self.assertEqual(action.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_permanent_errors_and_rate_limits(self):
        for error in [http_error(403, 'insufficientPermissions'), http_error(400), FileNotFoundError('missing')]:
            action = MagicMock(side_effect=error)
            with self.assertRaises(type(error)):
                ocr.network_retry(action, label='image')
            self.assertEqual(action.call_count, 1)
        self.assertTrue(ocr.transient_network_error(http_error(429)))
        self.assertTrue(ocr.transient_network_error(http_error(403, 'rateLimitExceeded')))

    @patch.object(ocr.time, 'sleep')
    def test_export_retried_without_uploading_again_and_cleanup_retried(self, sleep):
        service = MagicMock()
        service.files().create().execute.return_value = {'id': 'known-file'}
        service.files().delete().execute.side_effect = [http_error(500), None]
        class Downloader:
            def __init__(self, stream, request):
                self.stream, self.calls = stream, 0
            def next_chunk(self):
                self.calls += 1
                if self.calls == 1:
                    raise ConnectionResetError(10054, 'reset')
                self.stream.write('متن نامه'.encode('utf-8'))
                return None, True
        with patch.object(ocr, 'MediaIoBaseDownload', Downloader):
            result = ocr.ocr_single_media_gdrive(object(), 'letter.jpeg', 'image/jpeg', service,
                                               export_only=True, log_func=lambda _: None)
        self.assertEqual(result, 'متن نامه')
        self.assertEqual(service.files().create().execute.call_count, 1)
        self.assertEqual(service.files().delete().execute.call_count, 2)


if __name__ == '__main__':
    unittest.main()
