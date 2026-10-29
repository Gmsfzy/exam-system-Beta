<#
在线考试系统 - 一键启动（实现体）

- 入口是同目录的 start-all.bat（纯 ASCII 引导行），本文件承载全部逻辑与中文提示。
- 为什么这么拆：cmd.exe 在 UTF-8/CP65001 控制台下读含多字节字符的 .bat 会丢字节偏移，
  把后续行切碎当命令执行。v5.38 实测三组对照：纯中文行的 UTF-8 bat 仍报错，
  UTF-8 + 注释里的「>= 3.12。」还会在项目根生成名为「3.12。」的野文件；
  而 GBK+chcp 936 与纯 ASCII 两种写法都零报错。PowerShell 不受该问题影响，
  所以约定：.bat 侧保持零非 ASCII 字节，中文一律放这里。
- 本文件必须以「UTF-8 带 BOM」保存：Windows PowerShell 5.1 无 BOM 时按 ANSI 解码中文。
- 端口判据用 TCP 连接试探，比枚举监听表更贴近「这个端口还能不能用上」。
#>
param(
    [switch]$DryRun   # 只探测并打印将要执行的动作，不真正拉起服务（自测用）
)

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host '╔═══════════════════════════════════════════════╗'
Write-Host '║         在线考试系统 - 一键启动               ║'
Write-Host '╚═══════════════════════════════════════════════╝'
Write-Host ''

# ── Python 解释器检测：要求 3.12 以上（numpy 2.5 的依赖地板，v5.30 上调）──
# 顺序：PATH 中的 python / py → 常见安装绝对路径（312 在前，避免误命中旧环境）。
# 每个候选都用一次真实探针（读主次版本）验收，顺带过滤掉微软商店的占位 python。
# 探针只用 `--version`：PowerShell 5.1 向原生程序传参时会吞掉内嵌双引号，
# 实测 `-c 'print("%d.%d" ...)'` 到 Python 已变成没有引号的语法错误（v5.38 踩过）。
function Get-PythonVersion {
    param([string]$Exe)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # 避开原生 stderr 被包成 error record 抛 Stop
    try {
        $line = (& $Exe --version 2>$null) -join ' '
        if ($line -match 'Python\s+(\d+)\.(\d+)') {
            return [pscustomobject]@{ Major = [int]$Matches[1]; Minor = [int]$Matches[2] }
        }
    } catch { } finally {
        $ErrorActionPreference = $saved
    }
    return $null
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($name in @('python', 'py')) {
        foreach ($cmd in (Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($cmd.Source) { $candidates.Add($cmd.Source) }
        }
    }
    $local = $env:LOCALAPPDATA
    foreach ($v in @('312', '313', '314')) {
        foreach ($p in @(
            "D:\Python$v\python.exe",
            "C:\Python$v\python.exe",
            (Join-Path $local "Programs\Python\Python$v\python.exe")
        )) {
            if (Test-Path -LiteralPath $p) { $candidates.Add((Resolve-Path -LiteralPath $p).ProviderPath) }
        }
    }

    $tooOld = $null
    foreach ($exe in ($candidates | Select-Object -Unique)) {
        if ($exe -match '(?i)WindowsApps') { continue }   # 商店占位程序不是真解释器
        $ver = Get-PythonVersion -Exe $exe
        if (-not $ver) { continue }
        if ($ver.Major -gt 3 -or ($ver.Major -eq 3 -and $ver.Minor -ge 12)) {
            return [pscustomobject]@{ Exe = $exe; Version = $ver }
        }
        if (-not $tooOld) { $tooOld = [pscustomobject]@{ Exe = $exe; Version = $ver } }
    }
    return [pscustomobject]@{ Exe = $null; Version = $null; TooOld = $tooOld }
}

$found = Find-Python
if (-not $found.Exe) {
    if ($found.TooOld) {
        Write-Host '[错误] 检测到的 Python 版本过低，需要 3.12 或以上（numpy 2.5 依赖地板）：' -ForegroundColor Red
        Write-Host "       当前 $($found.TooOld.Version.Major).$($found.TooOld.Version.Minor)  $($found.TooOld.Exe)" -ForegroundColor Red
    } else {
        Write-Host '[错误] 未找到 Python 解释器。请确认已安装 Python 3.12 或以上，' -ForegroundColor Red
        Write-Host '       并将其加入 PATH，或修改本脚本的回退列表。' -ForegroundColor Red
    }
    if (-not $DryRun) { Read-Host '按回车键退出启动器' | Out-Null }
    exit 1
}

$pythonExe = $found.Exe
$pyVersion = "$($found.Version.Major).$($found.Version.Minor)"
Write-Host "[Python] 使用解释器: $pyVersion  $pythonExe"
Write-Host ''

# ── 端口占用探测：已连通就跳过并提示 PID，避免重复启动被误判成启动失败 ──
function Get-PortOwner {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $begin = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $begin.AsyncWaitHandle.WaitOne(250)) { return $null }
        $client.EndConnect($begin)
    } catch {
        return $null
    } finally {
        $client.Close()
    }
    try {
        $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
                Select-Object -First 1
        if ($conn) { return [string]$conn.OwningProcess }
    } catch { }
    return '未知'
}

function Invoke-ServiceStep {
    param([string]$Name, [string]$Label, [int]$Port, [string]$CommandLine)

    $owner = Get-PortOwner -Port $Port
    if ($owner) {
        Write-Host "[提示] 端口 $Port 已被进程 $owner 占用，跳过$Name。" -ForegroundColor Yellow
        Write-Host "       如需重启$Name，请先结束该进程或关掉它的窗口。" -ForegroundColor Yellow
        return
    }
    Write-Host $Label
    if ($DryRun) {
        Write-Host "[DryRun] 将新开窗口执行: $CommandLine" -ForegroundColor Cyan
        return
    }
    # 用 cmd /k 起独立窗口：服务报错时窗口保留，便于直接看启动日志
    Start-Process -FilePath $env:ComSpec -ArgumentList '/k', $CommandLine -WorkingDirectory $PSScriptRoot
}

Invoke-ServiceStep -Name '后端服务' -Label '[1/2] 启动后端服务，端口 5000 ...' -Port 5000 `
    -CommandLine "title 后端服务 && `"$pythonExe`" app.py"

# 后端先起来，避免前端首屏请求落空
Start-Sleep -Seconds 3

Invoke-ServiceStep -Name '前端服务' -Label '[2/2] 启动前端服务，端口 5173 ...' -Port 5173 `
    -CommandLine 'title 前端服务 && cd frontend && npm run dev'

Write-Host ''
Write-Host '服务启动完成！'
Write-Host ''
Write-Host '后端地址: http://localhost:5000'
Write-Host '前端地址: http://localhost:5173'
Write-Host '（后端默认开启 SPA 托管，只用 5000 单端口也能访问前端构建产物）'
Write-Host ''
if (-not $DryRun) { Read-Host '按回车键退出启动器' | Out-Null }
