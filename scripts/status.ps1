# 查看本地各服务当前状态：谁在跑、占用哪个端口、健康不健康
#
#   .\scripts\status.ps1
#
# 为什么要这个脚本：
#   后台进程没有窗口，`uv run embedding-server` 再起一次只会报
#   [Errno 10048] address already in use —— 端口冲突时先跑这个看清楚再决定。

$ErrorActionPreference = 'SilentlyContinue'

function Get-PortOwner {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen | Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
    return [pscustomobject]@{
        Pid     = $conn.OwningProcess
        Command = if ($proc.CommandLine) { $proc.CommandLine } else { '?' }
    }
}

function Probe {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
        return "HTTP $($r.StatusCode)"
    } catch {
        if ($_.Exception.Response) { return "HTTP $([int]$_.Exception.Response.StatusCode)" }
        return '不可达'
    }
}

Write-Host ''
Write-Host '应用服务' -ForegroundColor Cyan
Write-Host ('-' * 74) -ForegroundColor DarkGray

$apps = @(
    @{ Name = 'API';       Port = 8000; Url = 'http://127.0.0.1:8000/health' },
    @{ Name = 'Embedding'; Port = 8084; Url = 'http://127.0.0.1:8084/health' },
    @{ Name = 'Frontend';  Port = 5171; Url = 'http://localhost:5171/' }
)

foreach ($a in $apps) {
    $owner = Get-PortOwner -Port $a.Port
    if ($owner) {
        $state = Probe -Url $a.Url
        Write-Host ("  {0,-10} :{1,-5} pid={2,-7} {3}" -f $a.Name, $a.Port, $owner.Pid, $state) -ForegroundColor Green
        $cmd = $owner.Command
        if ($cmd.Length -gt 100) { $cmd = $cmd.Substring(0, 100) + '…' }
        Write-Host "             $cmd" -ForegroundColor DarkGray
    } else {
        Write-Host ("  {0,-10} :{1,-5} 未运行" -f $a.Name, $a.Port) -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host '基础设施（Docker）' -ForegroundColor Cyan
Write-Host ('-' * 74) -ForegroundColor DarkGray

$infra = @(
    @{ Name = 'PostgreSQL'; Port = 5432 },
    @{ Name = 'Redis';      Port = 6379 },
    @{ Name = 'MinIO';      Port = 9000 },
    @{ Name = 'Elasticsearch'; Port = 9200 },
    @{ Name = 'Milvus';     Port = 19530 }
)

foreach ($i in $infra) {
    # Docker Desktop(WSL2) 是端口转发，Get-NetTCPConnection 看不到，
    # 必须用真实 TCP 连接判断。
    $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $i.Port -InformationLevel Quiet -WarningAction SilentlyContinue
    $color = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("  {0,-14} :{1,-6} {2}" -f $i.Name, $i.Port, $(if ($ok) { '可达' } else { '不可达' })) -ForegroundColor $color
}

Write-Host ''
Write-Host '容器' -ForegroundColor Cyan
Write-Host ('-' * 74) -ForegroundColor DarkGray
docker ps --format '  {{.Names}}\t{{.Status}}' 2>$null

Write-Host ''
Write-Host '提示：想停掉全部应用进程用 .\scripts\dev-stop.ps1' -ForegroundColor DarkGray
Write-Host ''
