@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0"
set "PYTHON_EXE=E:\ProgramData\condaData\envs_dirs\steering_sim\python.exe"
set "ENV_ROOT=E:\ProgramData\condaData\envs_dirs\steering_sim"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Required Python was not found: %PYTHON_EXE%
  echo Check the steering_sim offline environment.
  pause
  exit /b 2
)

cd /d "%APP_ROOT%"
set "PYTHONPATH=%APP_ROOT%src;%APP_ROOT%"
set "PATH=%ENV_ROOT%;%ENV_ROOT%\Library\mingw-w64\bin;%ENV_ROOT%\Library\usr\bin;%ENV_ROOT%\Library\bin;%ENV_ROOT%\Scripts;%ENV_ROOT%\bin;%PATH%"
set "MPLBACKEND=Agg"

"%PYTHON_EXE%" "%APP_ROOT%scripts\d4\launch_desktop.py" --maximized %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Steering desktop failed with exit code %EXIT_CODE%.
  echo See outputs\desktop\logs for the complete startup log.
  pause
)
endlocal & exit /b %EXIT_CODE%
