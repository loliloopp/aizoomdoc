#!/bin/bash

# Script to migrate from Python 3.13 to Python 3.12
# Run: chmod +x migrate_to_python312.sh && ./migrate_to_python312.sh

echo "======================================"
echo "Python Version Migration Script"
echo "======================================"
echo ""

# Check if Python 3.12 is available
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')

echo "Current Python version: $PYTHON_VERSION"
echo ""

# Check if it's 3.12
if [[ $PYTHON_VERSION == 3.12* ]]; then
    echo "✓ Python 3.12 detected. Proceeding..."
else
    echo "ERROR: Python 3.12 not detected. Currently using: $PYTHON_VERSION"
    echo "Please install Python 3.12 first."
    echo "On macOS: brew install python@3.12"
    echo "On Ubuntu: sudo apt-get install python3.12 python3.12-venv"
    exit 1
fi

echo ""
echo "[1/4] Backing up old virtual environment..."
if [ -d "venv" ]; then
    rm -rf venv
    echo "Virtual environment removed."
else
    echo "Virtual environment not found (this is OK)."
fi
echo ""

echo "[2/4] Creating new virtual environment with Python 3.12..."
python3.12 -m venv venv
echo "Virtual environment created."
echo ""

echo "[3/4] Activating virtual environment..."
source venv/bin/activate
echo ""

echo "[4/4] Installing dependencies..."
pip install -r requirements.txt
echo ""

echo "======================================"
echo "Migration completed successfully!"
echo "======================================"
echo ""
echo "Your environment now uses Python 3.12"
echo "Virtual environment is activated."
echo ""

