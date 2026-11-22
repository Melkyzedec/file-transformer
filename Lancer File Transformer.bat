@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem ============================================================
rem  File Transformer - lanceur
rem
rem  Double-cliquez sur ce fichier pour demarrer l'application.
rem  Lancez-le avec l'argument "debug" pour garder la console
rem  ouverte et voir les messages d'erreur de Python.
rem ============================================================

set "DEBUG_MODE="
if /i "%~1"=="debug" set "DEBUG_MODE=1"

rem --- Recherche de Python (version console, pour les verifications) ---
set "PY_CONSOLE="
for %%C in (py.exe python.exe) do (
    if not defined PY_CONSOLE (
        where %%C >nul 2>&1 && set "PY_CONSOLE=%%C"
    )
)

if not defined PY_CONSOLE (
    echo.
    echo   [ERREUR] Python est introuvable sur cet ordinateur.
    echo.
    echo   Installez Python 3.10 ou plus recent depuis https://www.python.org/downloads/
    echo   et cochez "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

rem --- Verification des dependances ---
%PY_CONSOLE% -c "import webview, pypdfium2, xhtml2pdf, resvg_py" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [ERREUR] Les dependances Python ne sont pas installees.
    echo.
    echo   Installation en cours...
    echo.
    %PY_CONSOLE% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo   [ERREUR] L'installation a echoue. Lancez manuellement :
        echo       pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

if defined DEBUG_MODE goto :debug

rem --- Mode normal : pas de fenetre console ---
set "PY_WINDOWED="
for %%C in (pyw.exe pythonw.exe) do (
    if not defined PY_WINDOWED (
        where %%C >nul 2>&1 && set "PY_WINDOWED=%%C"
    )
)

if not defined PY_WINDOWED (
    rem Pas de pythonw disponible : on se rabat sur la version console.
    start "File Transformer" /min %PY_CONSOLE% "%~dp0main.py"
    exit /b 0
)

start "" %PY_WINDOWED% "%~dp0main.py"
exit /b 0

rem --- Mode debug : console visible, erreurs Python affichees ---
:debug
echo Demarrage de File Transformer en mode debug...
echo.
%PY_CONSOLE% "%~dp0main.py"
set "RC=%errorlevel%"
echo.
echo Application fermee (code de sortie : %RC%)
pause
exit /b %RC%
