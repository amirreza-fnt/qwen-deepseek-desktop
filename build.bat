@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name DeepSeekDesktop-Stable --add-data "dsk\wasm;dsk\wasm" --collect-all wasmtime --collect-all curl_cffi --hidden-import keyring.backends.Windows --hidden-import PySide6.QtWebEngineWidgets --hidden-import PySide6.QtWebEngineCore --hidden-import PySide6.QtSvg --collect-submodules markdown --collect-submodules pygments --add-data "app\assets;app\assets" main.py || exit /b 1
echo Built dist\DeepSeekDesktop-Stable\DeepSeekDesktop-Stable.exe



