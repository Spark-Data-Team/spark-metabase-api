#!/usr/bin/env bash
# Lance l'interface Streamlit du chatbot (autorat de dashboards Metabase).
#
# Usage :  ./run_chatbot.sh
# Puis ouvre http://localhost:8501 (le navigateur s'ouvre tout seul).
# Ctrl+C pour arrêter.
set -euo pipefail

# Toujours travailler depuis le dossier du repo, peu importe d'où on lance.
cd "$(dirname "$0")"

# Premier lancement (ou venv supprimé) : on (re)crée tout automatiquement.
if [ ! -x .venv/bin/streamlit ]; then
  echo "→ Création du venv et installation des dépendances (une seule fois)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install -e ".[streamlit,iac]"
fi

# Pré-remplit les identifiants Metabase depuis .env (domaine + session id).
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

echo "→ Interface : http://localhost:8501  (Ctrl+C pour arrêter)"
exec .venv/bin/streamlit run streamlit_app.py --browser.gatherUsageStats false
