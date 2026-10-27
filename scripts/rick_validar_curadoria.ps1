# Validação integrada Rick 02B2F — executar somente após checkout da branch.
# Não altera arquivos de configuração, não usa APIs pagas ou credenciais.
param([switch]$NoWebUI)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv não encontrado no PATH. Instale uv e reinicie o PowerShell."
}

$base = Join-Path $env:LOCALAPPDATA "Rick\pytest-curadoria-v2b2f"
New-Item -ItemType Directory -Force (Split-Path $base -Parent) | Out-Null

$tests = @(
    "test/services/test_rick_visual_curation.py",
    "test/services/test_rick_editorial_workspace.py",
    "test/services/test_rick_editorial_review.py",
    "test/services/test_rick_scene_timeline.py",
    "test/services/test_rick_pipeline.py",
    "test/services/test_rick_scene_pipeline.py",
    "test/services/test_webui_rick.py"
)
Write-Host "=== Rick 02B2F: testes offline ==="
& uv run pytest -q --tb=short --basetemp "$base" @tests
if ($LASTEXITCODE -ne 0) {
    throw "Houve falhas: não fazer merge. Envie o resumo do teste."
}
Write-Host "=== Testes concluídos sem falhas ===" -ForegroundColor Green

if (-not $NoWebUI) {
    Write-Host "Abrindo a WebUI local para conferir o painel de curadoria."
    & (Join-Path $root "webui.bat")
}
