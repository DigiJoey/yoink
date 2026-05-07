@echo off
cd /d "%~dp0"
echo Setting up YT Downloader...
echo.

set PYEXE=
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
if exist "C:\Program Files\Python313\python.exe" set PYEXE=C:\Program Files\Python313\python.exe
if "%PYEXE%"=="" (
    echo ERROR: Python 3.13 not found. Install with:
    echo   winget install Python.Python.3.13
    pause
    exit /b 1
)

if exist .venv rmdir /s /q .venv
"%PYEXE%" -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo Setup complete. Double-click launch.vbs to start the app.
pause
