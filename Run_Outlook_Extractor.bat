@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "MSG_INPUT=%~1"
if not defined MSG_INPUT set "MSG_INPUT=%~dp0test_inputs\msg"

py -3 offline_msg_pipeline.py --input "%MSG_INPUT%" --dataset offline_msg --ocr --rag
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Pipeline finished with errors. Exit code: %EXIT_CODE%
)

endlocal & exit /b %EXIT_CODE%
