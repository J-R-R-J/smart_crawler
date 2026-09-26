@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ====================================================
echo    SmartCrawler - Temporary Files Cleanup
echo ====================================================
echo.
echo    Default : code junk + build intermediates (regenerable)
echo    -a      : also runtime data (logs/exports/cookies) and release\*.zip
echo.

rem ---------- 1. Python bytecode cache ----------
rem .venv / .git are skipped on purpose: deleting bytecode there is pointless
rem and walking the virtual environment is what made this step slow.
echo [1/6] Removing __pycache__ folders (skipping .venv / .git) ...
set "N=0"
if exist "__pycache__" (
    rd /s /q "__pycache__" 2>nul
    set /a N+=1
)
for /d %%r in (*) do (
    if /i not "%%~nxr"==".venv" (
        if /i not "%%~nxr"==".git" (
            for /d /r "%%r" %%d in (__pycache__) do (
                if exist "%%d" rd /s /q "%%d" 2>nul
                set /a N+=1
            )
        )
    )
)
echo        Removed !N! folder(s)

rem ---------- 2. Temp dirs: pip / test / cache leftovers ----------
echo [2/6] Removing temp directories ...
for %%p in (.tmp .tmp2 .tmp3 .tmp4 .wheels .wheels2 .wheels3 .pytest_cache .mypy_cache .ruff_cache) do (
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
rem 只清项目自己的目录，避免扫 .venv / crawler_data（几万个文件，纯浪费时间）
echo [3/6] Removing .pyc / .pyo files ...
del /q *.pyc 2>nul
del /q *.pyo 2>nul
for %%d in (assets config core models tests tools ui utils) do (
    if exist "%%d" (
        del /s /q "%%d\*.pyc" 2>nul
        del /s /q "%%d\*.pyo" 2>nul
    )
)
echo        Done

rem ---------- 4. Temp logs / test leftovers ----------
echo [4/6] Removing temp logs and test leftovers ...
del /q *.log 2>nul
del /q *.part 2>nul
for %%f in (.e2e.log .feature.log .smoke.log .probe_load.log .probe_sp.log .probe_cookie.log .probe_ps.log .probe_diag.log .probe_profiles.log .probe_seq.log) do (
    if exist "%%f" del /q "%%f" 2>nul
)
rem 打包 / 校验过程留下的临时件（build\_verify_release.py 是仓库文件，保留）
if exist "build" (
    del /q "build\_*.log" 2>nul
    del /q "build\_tmp*" 2>nul
    for /d %%d in ("build\_tmp*") do rd /s /q "%%d" 2>nul
)
if exist "release" del /q "release\*.tmp" 2>nul
echo        Done

rem ---------- 5. Build intermediates（可重新生成） ----------
echo [5/6] Removing build intermediates (dist\, build\SmartCrawler\) ...
if exist "dist" (
    rd /s /q "dist" 2>nul
    if exist "dist" (
        echo        [SKIPPED] dist is locked. Close SmartCrawler.exe / stop PyInstaller, then retry.
    ) else (
        echo        Removed dist\
    )
)
if exist "build\SmartCrawler" (
    rd /s /q "build\SmartCrawler" 2>nul
    if exist "build\SmartCrawler" (
        echo        [SKIPPED] build\SmartCrawler is locked. Stop PyInstaller, then retry.
    ) else (
        echo        Removed build\SmartCrawler\
    )
)
echo        Keep: build\_verify_release.py, release\*.zip (用 -a 才删 release)

rem ---------- 6. Optional: runtime data + release zips ----------
if /i "%~1"=="-a"    goto :runtime
if /i "%~1"=="--all" goto :runtime
echo [6/6] Runtime data and release\*.zip skipped. Use "clean.bat -a" to clear logs/exports/cookies and the release zips.
goto :finish

:runtime
echo [6/6] Runtime data + release zips: logs / exports / cookies / caches / release\*.zip
choice /c YN /m "        Delete crawler_data logs/exports/cookies, caches and release zips"
if errorlevel 2 goto :finish
if exist "crawler_data\logs"    rd /s /q "crawler_data\logs"    2>nul
if exist "crawler_data\exports" rd /s /q "crawler_data\exports" 2>nul
if exist "crawler_data\cookies" rd /s /q "crawler_data\cookies" 2>nul
del /q "crawler_data\*adaptive*.db" 2>nul
if exist "release" (
    del /q "release\*.zip" 2>nul
    echo        Removed release\*.zip (要重新打包请跑 packaging\make_portable_zip.py 与 make_source_zip.py)
)
echo        Runtime data cleaned. Profiles and cookie sets were kept.

:finish
echo.
echo ====================================================
echo    Done. The .venv environment and program files
echo    were NOT touched. Source code / docs / packaging
echo    scripts are never deleted by this script.
echo ====================================================
echo.
pause
endlocal
