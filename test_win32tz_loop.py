# -*- coding: utf-8 -*-
import pythoncom
import win32com.client
import sys

pythoncom.CoInitialize()
outlook = win32com.client.Dispatch("Outlook.Application")
namespace = outlook.GetNamespace("MAPI")
inbox = namespace.GetDefaultFolder(6)
items = inbox.Items
print("Inbox items count:", items.Count)

for idx in range(1, min(10, items.Count + 1)):
    item = items.Item(idx)
    try:
        rx = item.ReceivedTime
        print(f"Item {idx}: rx={rx}, type={type(rx)}")
    except Exception as e:
        print(f"Item {idx} ReceivedTime ERROR:", e)
        import traceback
        traceback.print_exc()

pythoncom.CoUninitialize()
