@echo off
chcp 65001 >nul
title 在线考试系统 - 启动器

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║         在线考试系统 - 一键启动               ║
echo ╚═══════════════════════════════════════════════╝
echo.

:: ── Python 解释器自动检测（要求 3.12+，numpy==2.5.3 依赖地板，v5.30 上调）──
:: 优先用 PATH 中的 python；找不到则回退常见绝对路径。
:: 找到后校验版本：主次版本必须 >= 3.12。
setlocal enabledelayedexpansion
set "PYTHON_EXE="

:: 1) PATH 中的 python
for %%P in (python py) do (
    if not defined PYTHON_EXE (
        where %%P >nul 2>&1 && set "PYTHON_EXE=%%P"
    )
)

:: 2) 回退常见安装路径（按优先级，3.12 在前避免旧环境误命中）
if not defined PYTHON_EXE (
    for %%V in (312 313 314) do (
        if not defined PYTHON_EXE (
            if exist "D:\Python%%V\python.exe" set "PYTHON_EXE=D:\Python%%V\python.exe"
            if not defined PYTHON_EXE if exist "C:\Python%%V\python.exe" set "PYTHON_EXE=C:\Python%%V\python.exe"
            if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        )
    )
)

if not defined PYTHON_EXE (
    echo [错误] 未找到 Python 解释器。请确认已安装 Python 3.12 或以上，
    echo 并将其加入 PATH，或修改本脚本回退列表。
    pause
    exit /b 1
)

:: 版本校验（拒绝 < 3.12：numpy==2.5.3 要求 Python>=3.12，旧解释器装不上依赖）
%PYTHON_EXE% -c "import sys; v=sys.version_info; sys.exit(0 if (v.major,v.minor)>=(3,12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [错误] 检测到的 Python 版本过低，需要 3.12 或以上（numpy 2.5 依赖地板）：
    %PYTHON_EXE% --version
    pause
    exit /b 1
)

echo [Python] 使用解释器:
%PYTHON_EXE% --version
echo.

:: ── 启动后端服务 ──
echo [1/2] 启动后端服务 (端口: 5000)...
start "后端服务" cmd /k "%PYTHON_EXE% app.py"

:: 等待后端启动
timeout /t 3 /nobreak >nul

:: ── 启动前端服务 ──
echo [2/2] 启动前端服务 (端口: 5173)...
start "前端服务" cmd /k "cd frontend && npm run dev"

echo.
echo 服务启动完成！
echo.
echo 后端地址: http://localhost:5000
echo 前端地址: http://localhost:5173
echo.
echo 按任意键退出启动器...
pause >nul
