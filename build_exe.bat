@echo off
rem Construit ZwiftClickClavier.exe (a lancer dans le dossier contenant zwift_click_gui.py)
python -m pip install --upgrade bleak pynput cryptography pystray pillow pyinstaller
if errorlevel 1 goto erreur

python -m PyInstaller --noconfirm --onefile --windowed --uac-admin ^
  --name ClickBridge ^
  --icon logo.ico ^
  --add-data "logo.ico;." ^
  --collect-all bleak ^
  --collect-all pystray ^
  --collect-all PIL ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput._util.win32 ^
  zwift_click_gui.py
if errorlevel 1 goto erreur

echo.
echo Termine : dist\ZwiftClickClavier.exe
pause
exit /b 0

:erreur
echo.
echo Une etape a echoue, copie le message ci-dessus.
pause
exit /b 1
