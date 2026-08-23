# Console - Windows PowerShell launcher (equivalent to start.command / start.sh).
# Run it (or double-click) to listen on 127.0.0.1:9600 and open the browser.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files without
# a BOM using the system ANSI code page (here 936/GBK), so non-ASCII (e.g. Chinese)
# comments/strings can be mojibake. Keep this file ASCII to be safe on any locale.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Pick a real Python >= 3.12. We walk every interpreter on PATH (python, python3, py)
# and every location each one resolves to, skipping the Windows Store "App execution
# alias" stubs and any interpreter that is actually < 3.12. This keeps working even
# when a project/tool venv (e.g. a 3.11 one) is first on PATH.
function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($name in @("python", "python3", "py")) {
        $found = where.exe $name 2>$null
        foreach ($p in $found) {
            if ($p -and $p -notmatch 'WindowsApps') {
                $candidates.Add($p)
            }
        }
    }

    foreach ($p in ($candidates | Select-Object -Unique)) {
        try {
            $raw = & $p -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null
            $code = $LASTEXITCODE
            $v = ($raw | Select-Object -First 1)
            if ($code -eq 0 -and $v) {
                $version = $v -as [version]
                if ($version -and $version -ge [version]"3.12") {
                    return $p
                }
            }
        } catch {
            # Candidate is not runnable; try the next one.
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Error: no Python 3.12 or newer was found on PATH. Install Python 3.12+, or activate a conda environment with Python 3.12." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 127
}

& $py server.py
