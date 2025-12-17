@echo off
REM Setup script for Windows

echo ======================================
echo AIZoomDoc Setup Script
echo ======================================
echo.

REM Check Python version
echo [1/5] Checking Python version...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.12+
    pause
    exit /b 1
)
echo.

REM Create virtual environment
echo [2/5] Creating virtual environment...
if exist venv (
    echo Virtual environment already exists.
) else (
    python -m venv venv
    echo Virtual environment created.
)
echo.

REM Activate virtual environment and install dependencies
echo [3/5] Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
echo.

REM Create .env file if not exists
echo [4/5] Setting up configuration...
if exist .env (
    echo .env file already exists.
) else (
    echo Creating .env file from .env.example...
    copy .env.example .env
    echo.
    echo IMPORTANT: Edit .env file and add your OpenRouter API key!
)
echo.

REM Create data directory
echo [5/5] Creating data directories...
if not exist data mkdir data
if not exist data\viewports mkdir data\viewports
echo Data directories created.
echo.

echo ======================================
echo Setup completed successfully!
echo ======================================
echo.
echo Next steps:
echo 1. Edit .env file and add your OpenRouter API key
echo 2. Prepare your data in the data/ folder
echo 3. Run: python -m src.main "your query" --data-root ./data
echo.
pause

