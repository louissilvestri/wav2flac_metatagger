@echo off
rem Music Manager v2 — start server + open the app window
cd /d "%~dp0"
python -m server --open
pause
