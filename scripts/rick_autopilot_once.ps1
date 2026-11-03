# Rick daily autonomous controller (one local invocation).
# This file does not install a task or silently enable publishing.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$policy = Join-Path $root 'config\rick_daily.json'
if (-not (Test-Path -LiteralPath $policy -PathType Leaf)) {
    Write-Error 'Configure config\rick_daily.json (copy rick_daily.example.json first).'
    exit 2
}
& uv run --no-sync python -X utf8 -m app.services.rick_daily_autopilot `
    --policy $policy --state-dir (Join-Path $root 'storage\rick_autopilot') --execute
exit $LASTEXITCODE
