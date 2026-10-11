@echo off
rem ============================================================
rem  Electro-Hydraulic Steering Joint Simulation Platform
rem  One-click launcher. Offline. Does not use Amesim.
rem  This file is intentionally pure ASCII with CRLF endings:
rem  cmd.exe reads .bat files byte-wise in the OEM code page, and
rem  multi-byte text (especially after chcp 65001) makes it re-read
rem  the file at a wrong offset and tear lines apart.
rem  All Chinese output is produced by Python, which writes through
rem  the wide console API and is therefore encoding-safe.
rem ============================================================
setlocal EnableExtensions
set "PYTHON=E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe"
set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"
set "LAUNCHER=%PROJECT%\scripts\j0_demo\start_demo.py"

if not exist "%PYTHON%" goto :no_python
if not exist "%LAUNCHER%" goto :no_launcher

pushd "%PROJECT%"
"%PYTHON%" -X utf8 "%LAUNCHER%" %*
set "EXITCODE=%ERRORLEVEL%"
popd

if not "%EXITCODE%"=="0" goto :failed
endlocal
exit /b 0

:no_python
echo [START FAILED] The specified Python interpreter was not found:
echo     "%PYTHON%"
echo.
echo   Install/repair the steering_sim conda environment, or edit the
echo   PYTHON variable in this file.
echo.
powershell -NoProfile -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwA7AFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABdADoAOgBTAGgAbwB3ACgAJwAvVKhSMVkljRr/fmINTjBSB2OaW4R2IABQAHkAdABoAG8AbgAgAOOJypFoVgIwCgAKAB9nG2fvjYRfGv9FADoAXABQAHIAbwBnAHIAYQBtAEQAYQB0AGEAXABjAG8AbgBkAGEARABhAHQAYQBcAGUAbgB2AHMAXwBkAGkAcgBzAFwAcwB0AGUAZQByAGkAbgBnAF8AcwBpAG0AXABwAHkAdABoAG8AbgAuAGUAeABlAAoACgD3i254pIsgAHMAdABlAGUAcgBpAG4AZwBfAHMAaQBtACAAr3ODWFhbKFcM/xZi7k85ZSAAcwB0AGEAcgB0AF8AcwB0AGUAZQByAGkAbgBnAF8AZABlAG0AbwAuAGIAYQB0ACAALU6EdiAAUABZAFQASABPAE4AIADYU8+RAjAnACwAJwA1dbJtbI8RVPt8335UgAhU/04fd3Ne8FMnACwAJwBPAEsAJwAsACcARQByAHIAbwByACcAKQAgAHwAIABPAHUAdAAtAE4AdQBsAGwA
pause
exit /b 2

:no_launcher
echo [START FAILED] Launcher script not found:
echo     "%LAUNCHER%"
echo.
echo   Make sure this file sits in the project root and the project is complete.
echo.
powershell -NoProfile -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwA7AFsAUwB5AHMAdABlAG0ALgBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABdADoAOgBTAGgAbwB3ACgAJwAvVKhSMVkljRr/fmINTjBSL1SoUhqBLGcgAHMAYwByAGkAcAB0AHMAXABqADAAXwBkAGUAbQBvAFwAcwB0AGEAcgB0AF8AZABlAG0AbwAuAHAAeQACMAoACgD3i254pIssZ4dl9k5NT45OeZjudjlo7nZVXwz/FE55mO52h2X2ToxbdGUCMCcALAAnADV1sm1sjxFU+3zfflSACFT/Th93c17wUycALAAnAE8ASwAnACwAJwBFAHIAcgBvAHIAJwApACAAfAAgAE8AdQB0AC0ATgB1AGwAbAA=
pause
exit /b 3

:failed
echo.
echo [START FAILED] The platform did not start. Exit code %EXITCODE%.
echo   See the messages above for the reason.
echo.
pause
exit /b %EXITCODE%
