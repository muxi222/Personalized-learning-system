@echo off
REM =============================================================================
REM AI Learning Assistant - 启动脚本 (Windows)
REM
REM 用法:
REM   start.bat              启动所有服务
REM   start.bat api          仅启动 API 服务
REM   start.bat agent        仅启动 Agent Worker
REM   start.bat frontend     仅启动前端
REM   start.bat docker       使用 Docker Compose 启动
REM   start.bat stop         停止所有服务
REM =============================================================================

setlocal enabledelayedexpansion

REM 获取脚本目录
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..

REM 颜色不在 Windows CMD 中直接支持，使用前缀标识
set INFO=[INFO]
set SUCCESS=[SUCCESS]
set WARN=[WARN]
set ERROR=[ERROR]

REM 主入口
if "%1"=="" goto :all
if "%1"=="api" goto :api
if "%1"=="agent" goto :agent
if "%1"=="frontend" goto :frontend
if "%1"=="docker" goto :docker
if "%1"=="stop" goto :stop
if "%1"=="stop-docker" goto :stop_docker
if "%1"=="status" goto :status
if "%1"=="help" goto :help
if "%1"=="--help" goto :help
if "%1"=="-h" goto :help

echo %ERROR% 未知命令: %1
goto :help

:check_dependencies
echo %INFO% 检查依赖...

REM 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo %ERROR% Python 未安装
    exit /b 1
)

REM 检查 Node.js
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo %WARN% Node.js 未安装，前端服务将无法启动
)

echo %SUCCESS% 依赖检查完成
goto :eof

:setup_venv
echo %INFO% 设置 Python 虚拟环境...

if not exist "%PROJECT_ROOT%\.venv" (
    python -m venv "%PROJECT_ROOT%\.venv"
    echo %SUCCESS% 虚拟环境创建成功
)

call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"

REM 安装依赖
if exist "%PROJECT_ROOT%\pyproject.toml" (
    pip install -e "%PROJECT_ROOT%" -q
    echo %SUCCESS% 依赖安装完成
)
goto :eof

:setup_data_dirs
echo %INFO% 创建数据目录...
if not exist "%PROJECT_ROOT%\data\sqlite" mkdir "%PROJECT_ROOT%\data\sqlite"
if not exist "%PROJECT_ROOT%\data\faiss" mkdir "%PROJECT_ROOT%\data\faiss"
if not exist "%PROJECT_ROOT%\data\bm25" mkdir "%PROJECT_ROOT%\data\bm25"
if not exist "%PROJECT_ROOT%\data\uploads" mkdir "%PROJECT_ROOT%\data\uploads"
if not exist "%PROJECT_ROOT%\data\redis" mkdir "%PROJECT_ROOT%\data\redis"
if not exist "%PROJECT_ROOT%\logs" mkdir "%PROJECT_ROOT%\logs"
echo %SUCCESS% 数据目录创建完成
goto :eof

:load_env
if exist "%PROJECT_ROOT%\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%PROJECT_ROOT%\.env") do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" (
            set "%%a=%%b"
        )
    )
    echo %SUCCESS% 环境变量加载完成
) else (
    echo %WARN% .env 文件不存在，使用默认配置
    if exist "%PROJECT_ROOT%\env.example" (
        copy "%PROJECT_ROOT%\env.example" "%PROJECT_ROOT%\.env" >nul
        echo %INFO% 已从 env.example 创建 .env 文件，请编辑配置
    )
)
goto :eof

:api
echo %INFO% 启动 API 服务...
call :check_dependencies
call :setup_venv
call :load_env
call :setup_data_dirs

cd /d "%PROJECT_ROOT%"

REM 初始化数据库
python -c "from backend.app.db.session import init_db; import asyncio; asyncio.run(init_db()); print('数据库初始化完成')"

REM 设置 PYTHONPATH
set PYTHONPATH=%PROJECT_ROOT%

REM 获取端口
if not defined PORT set PORT=8000
if not defined HOST set HOST=0.0.0.0

echo %INFO% 启动 uvicorn...
start "API Server" cmd /c "uvicorn backend.main:app --host %HOST% --port %PORT% --reload"

echo %SUCCESS% API 服务启动成功
echo %INFO% 访问地址: http://localhost:%PORT%
echo %INFO% API 文档: http://localhost:%PORT%/docs
goto :eof

:agent
echo %INFO% 启动 Agent Worker...
call :check_dependencies
call :setup_venv
call :load_env

cd /d "%PROJECT_ROOT%"
set PYTHONPATH=%PROJECT_ROOT%

start "Agent Worker" cmd /c "celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo"

echo %SUCCESS% Agent Worker 启动成功
goto :eof

:frontend
echo %INFO% 启动前端服务...

where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo %ERROR% Node.js 未安装
    exit /b 1
)

cd /d "%PROJECT_ROOT%\frontend"

if not exist "node_modules" (
    echo %INFO% 安装前端依赖...
    call npm install
)

start "Frontend Server" cmd /c "npm run dev"

echo %SUCCESS% 前端服务启动成功
echo %INFO% 访问地址: http://localhost:3000
goto :eof

:docker
echo %INFO% 使用 Docker Compose 启动...

where docker >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo %ERROR% Docker 未安装
    exit /b 1
)

cd /d "%PROJECT_ROOT%"
call :setup_data_dirs

docker-compose up -d

echo %SUCCESS% Docker 服务启动成功
echo %INFO% API 地址: http://localhost:8000
echo %INFO% 前端地址: http://localhost:3000
goto :eof

:stop
echo %INFO% 停止所有服务...

REM 停止 uvicorn 进程
taskkill /F /FI "WINDOWTITLE eq API Server*" >nul 2>&1
taskkill /F /IM uvicorn.exe >nul 2>&1

REM 停止 Celery 进程
taskkill /F /FI "WINDOWTITLE eq Agent Worker*" >nul 2>&1
taskkill /F /IM celery.exe >nul 2>&1

REM 停止前端
taskkill /F /FI "WINDOWTITLE eq Frontend Server*" >nul 2>&1

echo %SUCCESS% 所有服务已停止
goto :eof

:stop_docker
echo %INFO% 停止 Docker 服务...
cd /d "%PROJECT_ROOT%"
docker-compose down
echo %SUCCESS% Docker 服务已停止
goto :eof

:status
echo.
echo ==========================================
echo       AI Learning Assistant 状态
echo ==========================================

REM 检查 API
tasklist /FI "IMAGENAME eq uvicorn.exe" 2>nul | find /I "uvicorn.exe" >nul
if %ERRORLEVEL%==0 (
    echo API 服务:     运行中
) else (
    echo API 服务:     未运行
)

REM 检查 Celery
tasklist /FI "IMAGENAME eq celery.exe" 2>nul | find /I "celery.exe" >nul
if %ERRORLEVEL%==0 (
    echo Agent Worker: 运行中
) else (
    echo Agent Worker: 未运行
)

echo ==========================================
goto :eof

:all
echo.
echo ==========================================
echo    AI Learning Assistant 启动脚本
echo ==========================================
echo.

call :check_dependencies
call :api
call :agent
call :frontend

echo.
call :status
goto :eof

:help
echo.
echo AI Learning Assistant 启动脚本 (Windows)
echo.
echo 用法: %~nx0 [命令]
echo.
echo 命令:
echo   (无参数)    启动所有服务 (API + Agent + 前端)
echo   api         仅启动 API 服务
echo   agent       仅启动 Agent Worker
echo   frontend    仅启动前端服务
echo   docker      使用 Docker Compose 启动
echo   stop        停止所有本地服务
echo   stop-docker 停止 Docker 服务
echo   status      显示服务状态
echo   help        显示此帮助
echo.
goto :eof

:end
endlocal
