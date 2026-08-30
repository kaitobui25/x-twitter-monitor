@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo X Monitor - Local Web Export Tool
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found. Run this file from the project root.
  pause
  exit /b 1
)

python -m src.webapp --root "%CD%"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Web server exited with code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
