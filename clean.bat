@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ====================================================
echo    SmartCrawler - Temporary Files Cleanup
echo ====================================================
echo.

rem ---------- 1. Python bytecode cache ----------
echo [1/5] Removing __pycache__ folders ...
set "N=0"
for /d /r . %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
    set /a N+=1
)
echo        Removed !N! folder(s)

rem ---------- 2. Temp dirs: pip / download leftovers ----------
echo [2/5] Removing temp directories ...
for %%p in (.tmp .tmp2 .tmp3 .tmp4 .wheels .wheels2 .wheels3 .pytest_cache .mypy_cache) do (
    if exist "%%p" (
        rd /s /q "%%p" 2>nul
        if exist "%%p" (
            echo        [SKIPPED] %%p is locked. Close related programs or reboot, then retry.
        ) else (
            echo        Removed %%p
        )
    )
)

rem ---------- 3. Compiled artifacts ----------
echo [3/5] Removing .pyc / .pyo files ...
del /s /q *.pyc 2>nul
del /s /q *.pyo 2>nul
echo        Done

rem ---------- 4. Temp logs / test leftovers ----------
echo [4/5] Removing temp logs and test leftovers ...
for %%f in (.e2e.log .feature.log .smoke.log .probe_load.log .probe_sp.log .probe_cookie.log .probe_ps.log .probe_diag.log .probe_profiles.log .probe_seq.log) do (
    if exist "%%f" del /q "%%f" 2>nul
)
del /q *.part 2>nul
echo        Done

rem ---------- 5. Optional: runtime data ----------
if /i "%~1"=="-a"    goto :runtime
if /i "%~1"=="--all" goto :runtime
echo [5/5] Runtime data skipped. Use "clean.bat -a" to also clear logs/exports/cookies.
goto :finish

:runtime
echo [5/5] Runtime data cleanup: logs / exports / cookies - profiles kept.
choice /c YN /m "        Delete crawler_data logs, exports and cookies"
if errorlevel 2 goto :finish
if exist "crawler_data\logs"    rd /s /q "crawler_data\logs"    2>nul
if exist "crawler_data\exports" rd /s /q "crawler_data\exports" 2>nul
if exist "crawler_data\cookies" rd /s /q "crawler_data\cookies" 2>nul
echo        Runtime data cleaned. Profiles and cookie sets were kept.

:finish
echo.
echo ====================================================
echo    Done. The .venv environment and program files
echo    were NOT touched.
echo ====================================================
echo.
pause
endlocal
