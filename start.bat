@echo off
setlocal

title tickflow-stock-panel
cd /d "%~dp0"

if exist "%USERPROFILE%\.local\bin" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if exist "%USERPROFILE%\.cargo\bin" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
if exist "%APPDATA%\npm" set "PATH=%APPDATA%\npm;%PATH%"
if exist "%LOCALAPPDATA%\pnpm" set "PATH=%LOCALAPPDATA%\pnpm;%PATH%"
if exist "%ProgramFiles%\nodejs" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%LOCALAPPDATA%\Programs\nodejs" set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"
if exist "D:\DevelopmentTool\nodejs20" set "PATH=D:\DevelopmentTool\nodejs20;%PATH%"

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo [start] PowerShell was not found.
    echo [start] Please run this script on Windows with PowerShell installed.
    pause
    exit /b 1
)

echo [start] Starting tickflow-stock-panel...
echo [start] Close the service with Ctrl+C in this window.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
    -File "%~dp0dev.ps1" %*

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [start] The service exited with code %EXIT_CODE%.
    pause
)

endlocal & exit /b %EXIT_CODE%
