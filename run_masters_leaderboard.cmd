@echo off
setlocal

REM Ensure we run from this script's directory.
cd /d "%~dp0"

set "PYTHON_EXE="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        set "PYTHON_EXE=py -3"
    ) else (
        where python >nul 2>&1
        if %errorlevel%==0 (
            set "PYTHON_EXE=python"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo Could not find Python.
    echo Install Python 3 and try again.
    exit /b 1
)

echo Starting Masters leaderboard...
%PYTHON_EXE% masters_leaderboard.py %*

exit /b %errorlevel%
