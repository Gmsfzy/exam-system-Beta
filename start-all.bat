@echo off
chcp 65001 >nul
title 在线考试系统 - 启动器

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║         在线考试系统 - 一键启动               ║
echo ╚═══════════════════════════════════════════════╝
echo.

:: 启动后端服务
echo [1/2] 启动后端服务 (端口: 5000)...
start "后端服务" cmd /k "D:\Python312\python.exe app.py"

:: 等待后端启动
timeout /t 3 /nobreak >nul

:: 启动前端服务
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