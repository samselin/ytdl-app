@echo off
echo.
echo   YTDL - by SamZ GFX
echo.
echo   Installing dependencies...
pip install -r requirements.txt -q
echo.
echo   Starting server at http://localhost:5000
echo   Open your browser and go to: http://localhost:5000
echo.
python app.py
pause
