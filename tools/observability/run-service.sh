#!/bin/sh
# Start ONE authenticated MLflow service profile on 127.0.0.1 inside a task-owned tmux socket.
#   run-service.sh <runtime-dir> [tmux-socket]
# The runtime dir must have been created with:
#   .venv/bin/python -m newton_observability.accounts init-profile --runtime <dir> --name <label> --port <port>
# Fails closed: no secrets.env / short admin password / missing secret key -> no server.
# Never binds a LAN address; never touches another profile's DB or artifacts; no cleanup.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="${1:?runtime dir required}"
SOCKET="${2:-newton-observability}"
PY="$HERE/.venv/bin/python"
"$PY" - "$RUNTIME" <<'PYEOF'
import sys
from pathlib import Path
from newton_observability.service import load_profile
load_profile(Path(sys.argv[1]))  # raises ProfileError when the profile cannot start closed
PYEOF
PORT="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]+'/profile.json'))['port'])" "$RUNTIME")"
NAME="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]+'/profile.json'))['name'])" "$RUNTIME")"
SESSION="mlflow-$NAME-$PORT"
if tmux -L "$SOCKET" has-session -t "$SESSION" 2>/dev/null; then
  echo "already running: tmux -L $SOCKET session $SESSION"; exit 0
fi
COMMAND="$("$PY" - "$PY" "$RUNTIME" <<'PYEOF'
import shlex,sys
print(shlex.join([sys.argv[1], "-m", "newton_observability.service", sys.argv[2]])
      + " >> " + shlex.quote(sys.argv[2] + "/server.log") + " 2>&1")
PYEOF
)"
tmux -L "$SOCKET" new-session -d -s "$SESSION" -c "$HERE" "$COMMAND"
echo "started: tmux -L $SOCKET attach -t $SESSION ; URL http://127.0.0.1:$PORT"
