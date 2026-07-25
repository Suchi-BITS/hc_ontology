#!/usr/bin/env bash
# Healthcare Ontology — setup & smoke test (Linux/macOS)

set -e
cd "$(dirname "$0")"

echo "==> Creating virtual environment (if needed)"
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate

echo "==> Installing dependencies"
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo "==> Copying .env.example -> .env"
  cp .env.example .env
  echo "    Edit .env with your Neo4j password and database name."
fi

echo "==> Checking Ollama"
if command -v ollama &>/dev/null; then
  ollama pull qwen2.5:latest || true
  ollama pull nomic-embed-text:latest || true
else
  echo "    Ollama not found — install from https://ollama.com"
fi

echo "==> Smoke test (import api)"
python -c "import api; print('API import OK')"

echo ""
echo "Done. Start services:"
echo "  uvicorn api:app --reload --host 127.0.0.1 --port 8000"
echo "  streamlit run streamlit_app.py"
echo "  Docs: http://127.0.0.1:8000/docs"
