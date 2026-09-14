<#
Vue3 在线考试系统 - 一键启动脚本
#>

$script:Title = "Vue3 在线考试系统"
$script:Port = 5173
$script:Url = "http://localhost:$Port"

function Write-ColorOutput {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::White
    )
    $originalColor = $Host.UI.RawUI.ForegroundColor
    $Host.UI.RawUI.ForegroundColor = $Color
    Write-Host $Message
    $Host.UI.RawUI.ForegroundColor = $originalColor
}

function Show-Header {
    Clear-Host
    Write-Host ""
    Write-ColorOutput "╔═══════════════════════════════════════════════╗" -Color Cyan
    Write-ColorOutput "║         $Title          ║" -Color Cyan
    Write-ColorOutput "╚═══════════════════════════════════════════════╝" -Color Cyan
    Write-Host ""
}

function Check-Dependencies {
    Write-ColorOutput "[检查] 检查 Node.js 环境..." -Color Yellow
    
    try {
        $nodeVersion = node --version
        Write-ColorOutput "[成功] Node.js 版本: $nodeVersion" -Color Green
    }
    catch {
        Write-ColorOutput "[错误] 未找到 Node.js，请先安装" -Color Red
        Write-Host ""
        Write-Host "下载地址: https://nodejs.org/"
        Read-Host "按任意键退出..."
        exit 1
    }

    Write-ColorOutput "[检查] 检查项目依赖..." -Color Yellow
    
    if (-not (Test-Path "node_modules")) {
        Write-ColorOutput "[提示] 缺少依赖，正在安装..." -Color Yellow
        Write-Host ""
        
        npm install
        
        if ($LASTEXITCODE -ne 0) {
            Write-ColorOutput "[错误] 依赖安装失败" -Color Red
            Read-Host "按任意键退出..."
            exit 1
        }
        
        Write-ColorOutput "[成功] 依赖安装完成" -Color Green
        Write-Host ""
    }
    else {
        Write-ColorOutput "[成功] 依赖已安装" -Color Green
    }
}

function Start-DevServer {
    Write-ColorOutput "[启动] 开发服务器..." -Color Yellow
    Write-Host ""
    Write-ColorOutput "访问地址: $Url" -Color Cyan
    Write-ColorOutput "按 Ctrl+C 停止服务" -Color Gray
    Write-Host ""

    npm run dev
}

# 主程序
Show-Header
Check-Dependencies
Start-DevServer