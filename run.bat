@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo    SmartCrawler launcher
echo ============================================
echo.

rem ---- prefer the bundled virtualenv ----
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

if "%PY%"=="python" goto :check_python
echo [info] Using virtualenv .venv
goto :check_pyside

:check_python
where python >nul 2>nul
if errorlevel 1 goto :no_python

:check_pyside
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 goto :install_deps
goto :launch

:install_deps
echo [info] PySide6 not found, installing dependencies ...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :no_deps
goto :launch

:launch
echo [info] Starting SmartCrawler ...
"%PY%" main.py
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [ERROR] SmartCrawler exited with code %RC%
if not "%RC%"=="0" echo         See crawler_data\logs\ for details.
goto :end

:no_python
echo [ERROR] Python was not found.
echo         Install Python 3.10+ and make sure it is on PATH.
goto :end

:no_deps
echo [ERROR] Dependency installation failed. Run it manually:
echo         "%PY%" -m pip install PySide6
goto :end

:end
echo.
pause
endlocal
