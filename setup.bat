@echo off
chcp 65001 >nul
echo ============================================
echo   A3 PaperCut Smart Split System - Setup
echo ============================================
echo.

REM Check Python 3.11
where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher ^(py^) not found.
    echo Please install Python 3.11 and ensure py command is available.
    pause
    exit /b 1
)

REM Step 1: Create venv
if exist ".venv\Scripts\python.exe" goto venv_done
echo [1/5] Creating Python 3.11 virtual environment...
call py -3.11 -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment creation failed.
    pause
    exit /b 1
)
goto venv_done
:venv_done
if exist ".venv\Scripts\python.exe" echo [1/5] Virtual environment ready.

REM Step 2: Upgrade pip
echo [2/5] Upgrading pip...
call .venv\Scripts\python.exe -m ensurepip --upgrade
call .venv\Scripts\python.exe -m pip install --upgrade pip

REM Step 3: Install Python dependencies
echo [3/5] Installing Python dependencies, this may take a while...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Some dependencies failed to install.
    echo [TIP] PaddleOCR packages are large, please be patient.
    pause
    exit /b 1
)

REM Step 4: Download OCR model
echo [4/5] Checking OCR model...
set "PADDLE_PDX_CACHE_HOME=%CD%\models"
if exist "models\official_models\PP-OCRv5_mobile_det_safetensors" goto model_done
echo Downloading model PP-OCRv5_mobile_det, please wait...
call .venv\Scripts\python.exe -c "import paddlex; paddlex.create_model('PP-OCRv5_mobile_det', engine='paddle_dynamic')"
if errorlevel 1 (
    echo [ERROR] Model download failed.
    echo Check network connection and try again.
    pause
    exit /b 1
)
echo Model downloaded successfully.
goto model_done
:model_done
if exist "models\official_models\PP-OCRv5_mobile_det_safetensors" echo Model ready.

REM Step 5: Install frontend dependencies
echo [5/5] Installing frontend dependencies...
cd frontend
if exist "node_modules" goto frontend_done
call npm.cmd install
if errorlevel 1 (
    echo [ERROR] Frontend dependency installation failed.
    cd ..
    pause
    exit /b 1
)
goto frontend_done
:frontend_done
cd ..

echo.
echo ============================================
echo   Setup complete!
echo   Run start.bat to launch the system.
echo ============================================
pause
