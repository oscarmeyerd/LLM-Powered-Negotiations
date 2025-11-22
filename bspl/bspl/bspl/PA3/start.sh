HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV="$HERE/../venv/bin/activate"
ENVFILE="$HERE/.env"

# Load .env file, if it exists
if [ -f "$ENVFILE" ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' "$ENVFILE" | xargs)
fi

# Check API keys
if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "OPENROUTER_API_KEY not set. Please export it or add to .env"
  exit 1
fi

# Activate venv, if available
if [ -f "$VENV" ]; then
  source "$VENV"
else
  echo "No virtual environment found at $VENV. Using system Python..."
fi

# Helper to start an agent in a new terminal
start_agent() {
  local script=$1
  if command -v gnome-terminal &>/dev/null; then
    gnome-terminal -- bash -c "cd '$HERE'; python '$script'; exec bash"
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    osascript -e "tell application \"Terminal\" to do script \"cd '$HERE'; source '$VENV'; python '$script'\""
  else
    echo "Starting $script in background..."
    (cd "$HERE" && python "$script") &
  fi
}

# Launch agents
start_agent "buyer.py"
start_agent "seller.py"
start_agent "shipper.py"

echo "All agents launched. Check individual windows for updates."