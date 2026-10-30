@echo off
title FaceTrack - Smart Face Recognition Attendance Management System
cd /d "%~dp0"

echo ==============================================================
echo   FaceTrack - Smart Face Recognition Attendance System
echo ==============================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python was not found in your PATH.
    echo Please install Python 3.12 from https://www.python.org/ and tick "Add Python to PATH".
    pause
    exit /b 1
)

python -c "import cv2, customtkinter, PIL, matplotlib, reportlab; assert hasattr(cv2, 'face')" >nul 2>nul
if %errorlevel% neq 0 (
    echo Installing required Python packages...
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Package installation failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

echo Launching FaceTrack...
python main.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] FaceTrack exited with an error. Check data\logs\facetrack.log for details.
    pause
)
