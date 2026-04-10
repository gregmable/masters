@echo off
setlocal

cd /d "%~dp0"

if not exist "dist\masters_leaderboard.exe" (
    echo Standalone executable not found at dist\masters_leaderboard.exe
    echo Build it first or use run_masters_leaderboard.cmd
    exit /b 1
)

echo Starting Masters leaderboard executable...
"dist\masters_leaderboard.exe" %*

exit /b %errorlevel%
