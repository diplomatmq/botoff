@echo off
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Python venv not found: %PY%
    echo Create it with:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
    echo Installing panel dependencies...
    pushd "%ROOT%frontend"
    call npm install
    popd
)

echo Applying database migrations...
pushd "%ROOT%backend"
"%PY%" -m alembic upgrade head
popd

echo Starting services...
start "portals-backend" /D "%ROOT%backend" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "portals-worker" /D "%ROOT%backend" cmd /k ""%PY%" -m app.worker.main"
start "portals-frontend" /D "%ROOT%frontend" cmd /k "set BACKEND_URL=http://127.0.0.1:8000&& npm run dev"

echo.
echo   Backend API : http://127.0.0.1:8000/healthz
echo   Panel       : http://localhost:3000   (login admin / admin)
echo.
echo Close the three opened windows to stop.
endlocal
