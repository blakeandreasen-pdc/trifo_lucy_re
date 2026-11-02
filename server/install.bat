@echo off
REM Lucy Local Control Server - install as auto-start
REM   * Adds Windows Firewall rules for ports 443, 80, 7990, 17766, 8080
REM   * Creates a Scheduled Task "LucyServer" that starts on boot
REM     (runs as SYSTEM, hidden, restarts if it crashes)
REM
REM Run as administrator.

setlocal

REM --- Self-elevate if not admin ------------------------------------------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting admin rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
set INSTALL_DIR=%cd%

REM --- Find Python --------------------------------------------------------
set PY_EXE=
for /f "delims=" %%i in ('where py 2^>nul') do if "%PY_EXE%"=="" set PY_EXE=%%i
if "%PY_EXE%"=="" for /f "delims=" %%i in ('where python 2^>nul') do if "%PY_EXE%"=="" set PY_EXE=%%i
if "%PY_EXE%"=="" (
    echo ERROR: Python not found. Install Python 3.8+ from https://python.org first.
    pause
    exit /b 1
)

echo Using Python: %PY_EXE%
echo Install dir : %INSTALL_DIR%
echo.

REM --- Install pyyaml -----------------------------------------------------
echo [1/4] Ensuring pyyaml is installed...
"%PY_EXE%" -m pip install --quiet pyyaml
if %errorlevel% neq 0 (
    echo WARNING: pyyaml install failed. The server may not start.
)

REM --- Firewall rules -----------------------------------------------------
echo [2/4] Adding Windows Firewall rules...
netsh advfirewall firewall delete rule name="Lucy Server" >nul 2>&1
netsh advfirewall firewall add rule name="Lucy Server" dir=in action=allow protocol=TCP localport=443,80,7990,17766,8080,9999 >nul
if %errorlevel% neq 0 (
    echo WARNING: firewall rule creation failed.
) else (
    echo   Opened TCP ports: 443, 80, 7990, 17766, 8080, 9999
)

REM --- Create scheduled task ---------------------------------------------
echo [3/4] Creating scheduled task "LucyServer"...
schtasks /query /tn "LucyServer" >nul 2>&1
if %errorlevel% equ 0 (
    echo   Removing existing task first...
    schtasks /delete /tn "LucyServer" /f >nul
)

REM Build task XML - gives us full control (restart on failure, run hidden, etc.)
set TASK_XML=%TEMP%\lucy_server_task.xml
(
    echo ^<?xml version="1.0" encoding="UTF-16"?^>
    echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
    echo   ^<RegistrationInfo^>
    echo     ^<Description^>Lucy Local Control Server^</Description^>
    echo   ^</RegistrationInfo^>
    echo   ^<Triggers^>
    echo     ^<BootTrigger^>
    echo       ^<Enabled^>true^</Enabled^>
    echo       ^<Delay^>PT30S^</Delay^>
    echo     ^</BootTrigger^>
    echo   ^</Triggers^>
    echo   ^<Principals^>
    echo     ^<Principal id="Author"^>
    echo       ^<UserId^>S-1-5-18^</UserId^>
    echo       ^<RunLevel^>HighestAvailable^</RunLevel^>
    echo     ^</Principal^>
    echo   ^</Principals^>
    echo   ^<Settings^>
    echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
    echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
    echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
    echo     ^<AllowHardTerminate^>true^</AllowHardTerminate^>
    echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^>
    echo     ^<RunOnlyIfNetworkAvailable^>true^</RunOnlyIfNetworkAvailable^>
    echo     ^<Enabled^>true^</Enabled^>
    echo     ^<Hidden^>true^</Hidden^>
    echo     ^<RestartOnFailure^>
    echo       ^<Interval^>PT1M^</Interval^>
    echo       ^<Count^>999^</Count^>
    echo     ^</RestartOnFailure^>
    echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^>
    echo   ^</Settings^>
    echo   ^<Actions Context="Author"^>
    echo     ^<Exec^>
    echo       ^<Command^>%PY_EXE%^</Command^>
    echo       ^<Arguments^>capture_server.py^</Arguments^>
    echo       ^<WorkingDirectory^>%INSTALL_DIR%^</WorkingDirectory^>
    echo     ^</Exec^>
    echo   ^</Actions^>
    echo ^</Task^>
) > "%TASK_XML%"

schtasks /create /tn "LucyServer" /xml "%TASK_XML%" /f >nul
if %errorlevel% neq 0 (
    echo ERROR: scheduled task creation failed.
    del "%TASK_XML%"
    pause
    exit /b 1
)
del "%TASK_XML%"
echo   Task created: runs on boot as SYSTEM, auto-restarts on failure.

REM --- Start it now -------------------------------------------------------
echo [4/4] Starting the server now...
schtasks /run /tn "LucyServer" >nul
if %errorlevel% equ 0 (
    echo   Server started in the background.
) else (
    echo   (Could not start task immediately. It will run at next boot.)
)

echo.
echo ============================================================
echo  Install complete.
echo.
echo  Server is running hidden in the background as SYSTEM.
echo  View log: type "%INSTALL_DIR%\capture_log.txt"
echo  Web UI  : http://localhost:8080/
echo.
echo  Next step: redirect Lucy's DNS. See SETUP.md for how.
echo.
echo  To uninstall, run uninstall.bat.
echo ============================================================
echo.
pause
