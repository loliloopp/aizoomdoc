#!/bin/bash

# Setup script for Linux/Mac

echo "======================================"
echo "AIZoomDoc Setup Script"
echo "======================================"
echo ""

# Check Python version
echo "[1/5] Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.12+"
    exit 1
fi
python3 --version
echo ""

# Create virtual environment
echo "[2/5] Creating virtual environment..."
if [ -d "venv" ]; then
    echo "Virtual environment already exists."
else
    python3 -m venv venv
    echo "Virtual environment created."
fi
echo ""

# Activate virtual environment and install dependencies
echo "[3/5] Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt
echo ""

# Create .env file if not exists
echo "[4/5] Setting up configuration..."
if [ -f ".env" ]; then
    echo ".env file already exists."
else
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env file and add your OpenRouter API key!"
fi
echo ""

# Create data directory
echo "[5/5] Creating data directories..."
mkdir -p data/viewports
echo "Data directories created."
echo ""

echo "======================================"
echo "Setup completed successfully!"
echo "======================================"
echo ""
echo "Next steps:"
echo "1. Edit .env file and add your OpenRouter API key"
echo "2. Prepare your data in the data/ folder"
echo "3. Run: python -m src.main \"your query\" --data-root ./data"
echo ""

