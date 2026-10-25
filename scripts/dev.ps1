# 一键启动本地开发环境的 4 个服务
#
#   .\scripts\dev.ps1              # 起 Docker 基础设施 + 3 个后端进程 + 前端
#   .\scripts\dev.ps1 -NoDocker    # 基础设施已经在跑，只起应用进程
#   .\scripts\dev.ps1 -NoFrontend  # 只起后端（前端自己另外开）
#
# 每个服务各占一个 PowerShell 窗口，日志实时可见。
# 停止：.\scripts\dev-stop.ps1
#
# 为什么是 4 个进程（不是 1 个）：
#   API        —— 只做 HTTP/SSE，必须随时可响应
#   embedding  —— bge-m3 常驻，模型只加载一次；API 与 worker 都通过 HTTP 调它
#   worker     —— 消费 Redis Stream 跑 MinerU 解析+切分+embedding+写库，单个 PDF 可能几分钟，
#                 绝不能放在请求链路里
#   frontend   —— Vite 开发服务器（仅开发期需要）
param(
    [switch]$NoDocker,
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }

# ── 0. 前置检查 ────────────────────────────────────────────
if (-not (Test-Path (Join-Path $backend '.venv'))) {
    throw "未找到 backend/.venv，请先在 backend 下执行 uv sync"
}

# ── 1. 基础设施（Docker）──────────────────────────────────
if (-not $NoDocker) {
    Write-Step '启动基础设施（postgres / redis / minio / es / milvus）'
    Push-Location $backend
    try {
        docker compose up -d
        if ($LASTEXITCODE -ne 0) { throw 'docker compose up 失败' }
        Write-Ok '基础设施已启动'
    } finally {
        Pop-Location
    }
}

# 等关键端口就绪（PG 5432 / Redis 6379 / MinIO 9000）
Write-Step '等待基础设施端口就绪'
$ports = @{ 5432 = 'PostgreSQL'; 6379 = 'Redis'; 9000 = 'MinIO' }
foreach ($p in $ports.Keys) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) {
            Write-Ok "端口 $p ($($ports[$p])) 就绪"
            break
        }
        Start-Sleep -Milliseconds 800
    }
}

# ── 2. 后端三个进程，各占一个窗口 ─────────────────────────
function Start-Window {
    param([string]$Title, [string]$WorkDir, [string]$Command)

    $inner = @"
`$Host.UI.RawUI.WindowTitle = '$Title'
Set-Location '$WorkDir'
Write-Host '── $Title ──' -ForegroundColor Cyan
$Command
Write-Host ''
Write-Host '进程已退出，按任意键关闭窗口' -ForegroundColor Yellow
`$null = `$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"@
    Start-Process -FilePath 'pwsh' -ArgumentList @('-NoProfile', '-NoExit', '-Command', $inner) | Out-Null
}

Write-Step '启动后端进程'
Start-Window -Title 'MedRAG API :8000' -WorkDir $backend -Command 'uv run medrag-api'
Start-Sleep -Milliseconds 400
Start-Window -Title 'MedRAG Embedding :8084' -WorkDir $backend -Command 'uv run embedding-server'
Start-Sleep -Milliseconds 400
Start-Window -Title 'MedRAG Worker (queue)' -WorkDir $backend -Command 'uv run pipeline-worker'
Write-Ok 'API / embedding / worker 已分别在独立窗口启动'

# ── 3. 前端 ───────────────────────────────────────────────
if (-not $NoFrontend) {
    Write-Step '启动前端（Vite）'
    if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
        Write-Host '    node_modules 不存在，先 npm install…' -ForegroundColor Yellow
        Push-Location $frontend
        try { npm install --legacy-peer-deps } finally { Pop-Location }
    }
    Start-Window -Title 'MedRAG Frontend :5171' -WorkDir $frontend -Command 'npm run dev'
    Write-Ok '前端已启动'
}

# ── 4. 汇总 ───────────────────────────────────────────────
Write-Host ''
Write-Host '────────────────────────────────────────────' -ForegroundColor DarkGray
Write-Host ' 前端     http://localhost:5171' -ForegroundColor White
Write-Host ' API      http://localhost:8000/docs' -ForegroundColor White
Write-Host ' Embedding http://localhost:8084/health' -ForegroundColor White
Write-Host ' Worker   看它自己的窗口（JSON 日志）' -ForegroundColor White
Write-Host '────────────────────────────────────────────' -ForegroundColor DarkGray
Write-Host ''
Write-Host '提示：日志是每行一个 JSON，想只看错误可以' -ForegroundColor DarkGray
Write-Host '      .\scripts\dev.ps1 后在各窗口用 $env:LOG_LEVEL="debug" 重启' -ForegroundColor DarkGray
Write-Host '停止：.\scripts\dev-stop.ps1' -ForegroundColor DarkGray
