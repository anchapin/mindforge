param(
    [switch]$CompoundOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $Root

try {
    if ($env:PYTHON) {
        $Python = $env:PYTHON
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = "python"
    }
    else {
        $Python = "python3"
    }

    $VerifyArgs = @("scripts/verify.py")
    if ($CompoundOnly) {
        $VerifyArgs += "--compound-only"
    }

    & $Python @VerifyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "scripts/verify.py failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
