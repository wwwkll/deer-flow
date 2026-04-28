@echo off
chcp 65001 >nul

echo.
echo ========================================
echo      Git Push Script (Skip Checks)
echo ========================================
echo.

REM Get current branch
for /f "tokens=*" %%i in ('git branch --show-current') do set BRANCH=%%i

if "%BRANCH%"=="" (
    echo ERROR: Not on any branch
    pause
    exit /b 1
)

echo Current branch: %BRANCH%
echo.

REM Ask for commit message
set /p MSG="Enter commit message (press Enter for default): "
if "%MSG%"=="" set MSG=Update code

echo.
echo Commit message: %MSG%
echo.

REM Step 1: Add files
echo [1/4] Adding files...
git add .

REM Step 2: Commit (skip checks)
echo [2/4] Committing code (skip checks)...
git commit -m "%MSG%" --no-verify

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Commit failed
    pause
    exit /b 1
)

REM Step 3: Push
echo [3/4] Pushing to remote...
git push origin %BRANCH%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Push failed
    pause
    exit /b 1
)

REM Step 4: Done
echo.
echo [4/4] Done!
echo.
echo ========================================
echo        Push Success!
echo ========================================
echo.
pause
