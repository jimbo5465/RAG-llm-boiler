@echo off
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
py -3 src\notebooklm_bundler_gui.py
if errorlevel 1 pause
