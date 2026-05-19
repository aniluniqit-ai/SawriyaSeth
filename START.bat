@echo off
title LKS WealthTech V21
color 0A
echo.
echo  ================================================
echo   LKS WealthTech V21 - Starting Desktop App
echo   OM NAMAH SHIVAY
echo  ================================================
echo.
cd /d "%~dp0"
python --version >nul 2>&1 || (echo Python install nahi hai! & pause & exit)
echo Installing / checking libraries...
pip install -r requirements.txt -q
echo.
start "" pythonw main_gui.py
exit

