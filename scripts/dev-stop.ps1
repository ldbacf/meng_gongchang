# 停止本地开发进程（API / embedding / worker / 前端）
#
#   .\scripts\dev-stop.ps1              # 只停应用进程，保留 Docker 基础设施
#   .\scripts\dev-stop.ps1 -IncludeDocker   # 连基础设施一起停
#
# 只杀本项目的进程（按命令行匹配），不会误伤你其他的 python / node。

param([switch]$IncludeDocker)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$patterns = @(
    @{ Name = 'API'; Norm = 'medrag-api' },
    @{ Name = 'API'; Norm = 'app.run_api' },
    @{ Name = 'Embedding'; Norm = 'embedding-server' },
    @{ Name = 'Embedding'; Norm = 'app.application.embedding_server' },
    @{ Name = 'Worker'; Norm = 'pipeline-worker' },
    @{ Name = 'Worker'; Norm = 'app.application.worker' },
    @{ Name = 'Frontend'; Norm = 'vite' }
)

$killed = @()
foreach ($proc in Get-CimInstance Win32_Process) {
    $cmd = $proc.CommandLine
    if (-not $cmd) { continue }
    # 只处理属于本项目目录的进程，避免杀掉别的 vite / python
    if ($cmd -notlike "*$root*" -and $cmd -notlike '*medrag*' -and $cmd -notlike '*embedding_server*') { continue }

    foreach ($p in $patterns) {
        if ($cmd -like "*$($p.Norm)*") {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                $killed += "$($p.Name) (pid=$($proc.ProcessId))"
            } catch {
                # 已经退出或权限不足，跳过
            }
            break
        }
    }
}

if ($killed.Count) {
    $killed | ForEach-Object { Write-Host "  已停止 $_" -ForegroundColor Green }
} else {
    Write-Host '  没有找到运行中的项目进程' -ForegroundColor Yellow
}

# 端口确认
$ports = @{ 8000 = 'API'; 8084 = 'Embedding'; 5171 = 'Frontend' }
foreach ($p in $ports.Keys) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    if ($conn) { Write-Host "  端口 $p ($($ports[$p])) 仍被占用" -ForegroundColor Yellow }
    else { Write-Host "  端口 $p ($($ports[$p])) 已释放" -ForegroundColor DarkGray }
}

if ($IncludeDocker) {
    $backend = Join-Path $root 'backend'
    if (Test-Path $backend) {
        Write-Host '==> 停止基础设施' -ForegroundColor Cyan
        Push-Location $backend
        try { docker compose down } finally { Pop-Location }
    }
}
