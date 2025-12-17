@echo off
REM Example run script for Windows

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Running example query...
echo.

python -m src.main "Найди всё вентиляционное оборудование на листах" --data-root ./data

echo.
pause

