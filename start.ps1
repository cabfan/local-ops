# 总控台 (Console) — Windows PowerShell 启动脚本
# 等价于 macOS 的 start.command / Linux 的 start.sh。
# 双击运行或在 PowerShell 中执行：监听 127.0.0.1:9600 并自动打开浏览器。
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $py = $candidate
        break
    }
}
if (-not $py) {
    Write-Host "错误：未找到 Python 3，请先安装 Python 3.12 或更高版本。" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 127
}

& $py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误：总控台需要 Python 3.12 或更高版本。" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 126
}

& $py server.py
