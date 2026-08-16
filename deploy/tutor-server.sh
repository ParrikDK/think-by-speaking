#!/usr/bin/env bash
# Tutor Server control script — start/stop/status/logs for the
# "Speak, Don't Just Read" backend (serves the built frontend on :8000).
# Used by the double-clickable "Tutor Server.app" (see make-tutor-app.sh),
# and works standalone:  ./deploy/tutor-server.sh {start|stop|restart|status|logs|open}
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
PYTHON="$BACKEND_DIR/venv/bin/python"
PIDFILE="$BACKEND_DIR/tutor-server.pid"
LOGFILE="$BACKEND_DIR/logs/tutor-server.log"
PORT="${TUTOR_PORT:-8000}"
URL="http://localhost:$PORT"

if [ ! -x "$PYTHON" ]; then
  echo "Backend venv not found at $PYTHON — run the setup steps in README.md first."
  exit 1
fi

is_running() {
  # pidfile with a live process?
  if [ -f "$PIDFILE" ]; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  # port already serving (e.g. a server started without the pidfile)?
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

pid_of_port() {
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1
}

start() {
  if is_running; then
    echo "Already running — $URL"
    return 0
  fi
  mkdir -p "$BACKEND_DIR/logs"
  cd "$BACKEND_DIR"
  nohup "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >>"$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 40); do
    if curl -sf "$URL/api/health" >/dev/null 2>&1; then
      echo "Started — $URL (pid $(cat "$PIDFILE"))"
      return 0
    fi
    sleep 0.5
  done
  echo "Server did not become healthy — see $LOGFILE"
  return 1
}

stop() {
  if ! is_running; then
    echo "Not running."
    return 0
  fi
  local pid
  pid="$(cat "$PIDFILE" 2>/dev/null || pid_of_port)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.3
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "Graceful kill timed out — sending SIGKILL"
      kill -9 "$pid"
    fi
  fi
  rm -f "$PIDFILE"
  echo "Stopped."
}

restart() { stop; start; }

status() {
  if is_running; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || pid_of_port)"
    echo "Running — $URL (pid ${pid:-unknown})"
  else
    echo "Not running."
  fi
}

logs() {
  if [ -f "$LOGFILE" ]; then
    tail -n 25 "$LOGFILE"
  else
    echo "No log yet — start the server first."
  fi
}

open_dashboard() { open "$URL"; }

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) restart ;;
  status)  status ;;
  logs)    logs ;;
  open)    open_dashboard ;;
  *) echo "Usage: $0 {start|stop|restart|status|logs|open}"; exit 1 ;;
esac
