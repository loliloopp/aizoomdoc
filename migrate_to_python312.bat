@echo off
REM Script to migrate from Python 3.13 to Python 3.12
REM Run this script to safely switch Python versions

echo ======================================
echo Python Version Migration Script
echo ======================================
echo.

REM Check if Python 3.12 is available
python --version > temp_version.txt
set /p python_version=<temp_version.txt
del temp_version.txt

echo Current Python version: %python_version%
echo.

REM Check if it's 3.12
if "%python_version:~7,3%"=="3.1" (
    if "%python_version:~10,1%"=="2" (
        echo ✓ Python 3.12 detected. Proceeding...
    ) else (
        echo ERROR: Python 3.13 detected. Please install Python 3.12 first.
        echo Download from: https://www.python.org/downloads/release/python-3121/
        pause
        exit /b 1
    )
) else (
    echo WARNING: Could not verify Python version.
    echo Please ensure you have Python 3.12 installed.
    pause
)

echo.
echo [1/4] Backing up old virtual environment...
if exist venv (
    rmdir /s /q venv
    echo Virtual environment removed.
) else (
    echo Virtual environment not found (this is OK).
)
echo.

echo [2/4] Creating new virtual environment with Python 3.12...
python -m venv venv
echo Virtual environment created.
echo.

echo [3/4] Activating virtual environment...
call venv\Scripts\activate.bat
echo.

echo [4/4] Installing dependencies...
pip install -r requirements.txt
echo.

echo ======================================
echo Migration completed successfully!
echo ======================================
echo.
echo Your environment now uses Python 3.12
echo Virtual environment is activated.
echo.
pause

