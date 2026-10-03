# -*- coding: utf-8 -*-
import sys

print("Python version:", sys.version)
try:
    import cv2
    print("cv2:", cv2.__version__)
except Exception as e:
    print("cv2 not found:", e)

try:
    import PIL
    print("Pillow:", PIL.__version__)
except Exception as e:
    print("Pillow not found:", e)
