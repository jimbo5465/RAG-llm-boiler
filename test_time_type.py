# -*- coding: utf-8 -*-
import win32com.client
import pythoncom
import datetime

pythoncom.CoInitialize()
outlook = win32com.client.Dispatch("Outlook.Application")
namespace = outlook.GetNamespace("MAPI")
inbox = namespace.GetDefaultFolder(6)
items = inbox.Items
print("Total items in Inbox:", items.Count)

for i in range(1, min(5, items.Count + 1)):
    item = items.Item(i)
    try:
        rx = item.ReceivedTime
        print(f"Item {i}: rx_type={type(rx)}, val={rx}")
        if hasattr(rx, 'year'):
            print(f"  year={rx.year}, month={rx.month}, day={rx.day}")
    except Exception as e:
        print(f"Item {i} error: {e}")
