@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1

if not exist "main.py" goto :incomplete
if not exist "requirements.txt" goto :incomplete

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if exist ".venv" goto :check_venv

set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "BOOTSTRAP="
set "BOOTSTRAP_ARGS="
if exist ".runtime\python\python.exe" call :probe "%CD%\.runtime\python\python.exe"
if not defined BOOTSTRAP call :probe_launcher
if not defined BOOTSTRAP for /f "delims=" %%P in ('"%SystemRoot%\System32\where.exe" $PATH:python.exe 2^>nul') do if not defined BOOTSTRAP call :probe_path "%%P"
if not defined BOOTSTRAP goto :missing_python

echo [File Transformer] Creation de l'environnement Python local...
"%BOOTSTRAP%" %BOOTSTRAP_ARGS% -m venv ".venv"
if errorlevel 1 goto :venv_creation_failed

:check_venv
if not exist "%VENV_PYTHON%" goto :broken_venv
"%VENV_PYTHON%" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto :broken_venv

"%VENV_PYTHON%" -c "import webview, PIL, pypdfium2, xhtml2pdf, resvg_py, docx, markdown, reportlab, pillow_heif, imagecodecs, numpy" >nul 2>&1
if not errorlevel 1 goto :launch

echo [File Transformer] Installation des dependances dans .venv...
"%VENV_PYTHON%" -m pip install -r "requirements.txt"
if errorlevel 1 goto :dependencies_failed
"%VENV_PYTHON%" -c "import webview, PIL, pypdfium2, xhtml2pdf, resvg_py, docx, markdown, reportlab, pillow_heif, imagecodecs, numpy"
if errorlevel 1 goto :dependencies_failed

:launch
if /i "%~1"=="debug" goto :debug
if not exist ".venv\Scripts\pythonw.exe" goto :debug
start "" "%CD%\.venv\Scripts\pythonw.exe" "%CD%\main.py"
exit /b %errorlevel%

:debug
echo [File Transformer] Demarrage avec "%VENV_PYTHON%".
"%VENV_PYTHON%" "%CD%\main.py"
set "RC=%errorlevel%"
echo [File Transformer] Application fermee, code %RC%.
pause
exit /b %RC%

:probe_launcher
for /f "delims=" %%P in ('"%SystemRoot%\System32\where.exe" $PATH:py.exe 2^>nul') do if not defined BOOTSTRAP call :probe "%%P" -3
if defined BOOTSTRAP exit /b 0
exit /b 1

:probe_path
rem Ignorer l'alias du Microsoft Store quand aucun Python n'est installe.
if /i "%~dp1"=="%LOCALAPPDATA%\Microsoft\WindowsApps\" exit /b 1
call :probe "%~1"
exit /b %errorlevel%

:probe
"%~1" %~2 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 exit /b 1
set "BOOTSTRAP=%~1"
set "BOOTSTRAP_ARGS=%~2"
exit /b 0

:incomplete
echo [ERREUR] Dossier incomplet. Utilisez Extraire tout, puis ouvrez le dossier qui contient main.py et requirements.txt.
goto :failed

:missing_python
echo [ERREUR] Python 3.10 ou plus recent est requis. Installez Python 3.14 x64 pour votre compte, puis relancez ce fichier.
echo https://www.python.org/downloads/windows/
goto :failed

:broken_venv
echo [ERREUR] Le dossier .venv ne contient pas un Python utilisable. Renommez .venv en .venv-ancienne puis relancez.
goto :failed

:venv_creation_failed
echo [ERREUR] Impossible de creer .venv. Verifiez que le dossier extrait est accessible en ecriture.
echo Si un dossier .venv incomplet a ete cree, renommez-le avant de reessayer.
goto :failed

:dependencies_failed
echo [ERREUR] Installation ou chargement des dependances impossible. Verifiez le message affiche et la connexion Internet.
goto :failed

:failed
pause
exit /b 1
