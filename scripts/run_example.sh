#!/bin/bash

# Example run script for Linux/Mac

echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Running example query..."
echo ""

python -m src.main "Найди всё вентиляционное оборудование на листах" --data-root ./data

echo ""

