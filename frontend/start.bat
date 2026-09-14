@echo off
chcp 65001 >nul
echo.
echo ================================
echo    Vue3 在线考试系统 - 开发模式
echo ================================
echo.
echo 正在启动开发服务器...
echo.

cd /d "%~dp0"

if not exist node_modules (
    echo 检测到缺少依赖，正在安装...
    echo.
    npm install
    echo.
)

echo 启动开发服务器 (http://localhost:5173)
echo 按 Ctrl+C 停止服务
echo.
npm run dev

pause