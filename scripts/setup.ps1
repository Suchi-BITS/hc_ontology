# Healthcare Ontology — setup & smoke test (Windows PowerShell)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "==> Creating virtual environment (if needed)"
if (-not (Test-Path venv)) { python -m venv venv }
& .\venv\Scripts\Activate.ps1

Write-Host "==> Installing dependencies"
pip install -q -r requirements.txt

if (-not (Test-Path .env)) {
    Write-Host "==> Copying .env.example -> .env"
    Copy-Item .env.example .env
    Write-Host "    Edit .env with your Neo4j password and database name."
}

Write-Host "==> Checking Ollama"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    ollama pull qwen2.5:latest
    ollama pull nomic-embed-text:latest
} else {
    Write-Host "    Ollama not found — install from https://ollama.com"
}

Write-Host "==> Smoke test (import api)"
python -c "import api; print('API import OK')"

Write-Host ""
Write-Host "Done. Start services:"
Write-Host "  uvicorn api:app --reload --host 127.0.0.1 --port 8000"
Write-Host "  streamlit run streamlit_app.py"
Write-Host "  Docs: http://127.0.0.1:8000/docs"
