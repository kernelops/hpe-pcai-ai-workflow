#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  HPE PCAI — Full Stack Launcher
#  Starts all 5 services with a single command.
#
#  Usage:
#    ./start.sh           # Start everything
#    ./start.sh --no-airflow   # Skip Airflow (Docker)
#    ./start.sh --stop    # Stop all services
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$REPO_ROOT/.venv"
PID_DIR="$REPO_ROOT/.pids"
LOG_DIR="$REPO_ROOT/.service_logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────

log()  { echo -e "${CYAN}[LAUNCHER]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✅ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠️  $*${NC}"; }
err()  { echo -e "${RED}  ❌ $*${NC}"; }

wait_for_port() {
    local name="$1" port="$2" max_wait="${3:-30}"
    local elapsed=0
    while ! ss -tlnp 2>/dev/null | grep -q ":${port} " && [ $elapsed -lt $max_wait ]; do
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if [ $elapsed -ge $max_wait ]; then
        warn "$name did not start on port $port within ${max_wait}s"
        return 1
    fi
    ok "$name is up on port $port"
    return 0
}

save_pid() {
    echo "$2" > "$PID_DIR/$1.pid"
}

read_pid() {
    local f="$PID_DIR/$1.pid"
    [ -f "$f" ] && cat "$f" || echo ""
}

is_running() {
    local pid
    pid="$(read_pid "$1")"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# ── Stop all ──────────────────────────────────────────────────

stop_all() {
    log "Stopping all services..."
    echo ""

    # Stop Python services
    for svc in rag agent_api backend rq_worker; do
        local pid
        pid="$(read_pid "$svc")"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            # Also kill children (uvicorn/rq workers)
            pkill -P "$pid" 2>/dev/null || true
            ok "Stopped $svc (PID $pid)"
        else
            echo "  · $svc not running"
        fi
        rm -f "$PID_DIR/$svc.pid"
    done

    # Stop frontend
    local fpid
    fpid="$(read_pid "frontend")"
    if [ -n "$fpid" ] && kill -0 "$fpid" 2>/dev/null; then
        kill "$fpid" 2>/dev/null || true
        pkill -P "$fpid" 2>/dev/null || true
        ok "Stopped frontend (PID $fpid)"
    else
        echo "  · frontend not running"
    fi
    rm -f "$PID_DIR/frontend.pid"

    # Stop Airflow
    if [ -f "$REPO_ROOT/airflow/docker-compose.yaml" ]; then
        log "Stopping Airflow containers..."
        (cd "$REPO_ROOT/airflow" && docker compose down 2>/dev/null) || true
        ok "Airflow stopped"
    fi

    echo ""
    log "All services stopped."
    exit 0
}

# ── Parse args ────────────────────────────────────────────────

SKIP_AIRFLOW=false
for arg in "$@"; do
    case "$arg" in
        --stop)       stop_all ;;
        --no-airflow) SKIP_AIRFLOW=true ;;
        --help|-h)
            echo "Usage: $0 [--no-airflow] [--stop]"
            exit 0
            ;;
    esac
done

# ── Pre-flight checks ────────────────────────────────────────

mkdir -p "$PID_DIR" "$LOG_DIR"

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  🚀 HPE PCAI — Full Stack Launcher${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo ""

# Check venv
if [ ! -d "$VENV" ]; then
    err "Python venv not found at $VENV"
    echo "  Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check node_modules
if [ ! -d "$REPO_ROOT/frontend/node_modules" ]; then
    warn "Frontend node_modules not found. Installing..."
    (cd "$REPO_ROOT/frontend" && npm install)
fi

# ── Service 1: Airflow (Docker) ──────────────────────────────

if [ "$SKIP_AIRFLOW" = false ]; then
    log "Starting Airflow (Docker Compose)..."

    cd "$REPO_ROOT/airflow"
    echo "AIRFLOW_UID=$(id -u)" > .env
    mkdir -p logs config plugins

    docker compose up -d >> "$LOG_DIR/airflow.log" 2>&1

    # Wait for webserver to be ready
    log "Waiting for Airflow webserver (port 8080)..."
    airflow_ready=false
    for i in $(seq 1 60); do
        if curl -sf -u airflow:airflow http://127.0.0.1:8080/api/v1/health > /dev/null 2>&1; then
            airflow_ready=true
            break
        fi
        sleep 2
    done

    if [ "$airflow_ready" = true ]; then
        ok "Airflow is up on http://127.0.0.1:8080"
        # Unpause the DAG
        docker compose exec -T airflow-webserver airflow dags unpause deployment_workflow > /dev/null 2>&1 || true
        ok "deployment_workflow DAG unpaused"
    else
        warn "Airflow didn't start within 120s — check: cd airflow && docker compose logs"
    fi

    cd "$REPO_ROOT"
else
    log "Skipping Airflow (--no-airflow)"
fi

# ── Service 2: RAG Service (port 8002) ───────────────────────

log "Starting RAG Service on port 8002..."

if is_running rag; then
    warn "RAG already running (PID $(read_pid rag))"
else
    RAG_FORCE_LOCAL_EMBEDDINGS=1 \
    "$VENV/bin/python" -m uvicorn rag.main:app \
        --host 0.0.0.0 --port 8002 \
        >> "$LOG_DIR/rag.log" 2>&1 &
    save_pid rag $!
    wait_for_port "RAG Service" 8002 20
fi

# ── Service 3: Agent API (port 8001) ─────────────────────────

log "Starting Agent API on port 8001..."

if is_running agent_api; then
    warn "Agent API already running (PID $(read_pid agent_api))"
else
    RAG_API_URL=http://127.0.0.1:8002 \
    "$VENV/bin/python" -m uvicorn api.main:app \
        --host 0.0.0.0 --port 8001 \
        >> "$LOG_DIR/agent_api.log" 2>&1 &
    save_pid agent_api $!
    wait_for_port "Agent API" 8001 20
fi

# ── Service 4: Backend API (port 8000) ───────────────────────

log "Starting Backend API on port 8000..."

if is_running backend; then
    warn "Backend already running (PID $(read_pid backend))"
else
    AIRFLOW_BASE_URL=http://127.0.0.1:8080 \
    AIRFLOW_DAG_ID=deployment_workflow \
    AIRFLOW_USERNAME=airflow \
    AIRFLOW_PASSWORD=airflow \
    AGENT_OPS_API_URL=http://127.0.0.1:8001/api/agents/analyze-failure \
    AGENT_OPS_BASE_URL=http://127.0.0.1:8001 \
    AIRFLOW_LOGS_PATH="$REPO_ROOT/airflow/logs" \
    "$VENV/bin/python" -m uvicorn backend.main:app \
        --host 0.0.0.0 --port 8000 \
        >> "$LOG_DIR/backend.log" 2>&1 &
    save_pid backend $!
    wait_for_port "Backend API" 8000 20
fi

# ── Service 5: RQ Worker (Phase 3 HPC Queue) ─────────────────────

log "Starting RQ Worker for HPC Error Logs..."

if is_running rq_worker; then
    warn "RQ Worker already running (PID $(read_pid rq_worker))"
else
    cd "$REPO_ROOT"
    PYTHONPATH="$REPO_ROOT" "$VENV/bin/rq" worker hpc_error_logs \
        --url redis://localhost:6379/0 \
        >> "$LOG_DIR/rq_worker.log" 2>&1 &
    save_pid rq_worker $!
    ok "RQ Worker is up"
fi

# ── Service 5: Frontend (port 5173) ──────────────────────────

log "Starting Frontend on port 5173..."

if is_running frontend; then
    warn "Frontend already running (PID $(read_pid frontend))"
else
    cd "$REPO_ROOT/frontend"
    VITE_API_BASE_URL=http://127.0.0.1:8000 \
    npx vite --host 0.0.0.0 --port 5173 \
        >> "$LOG_DIR/frontend.log" 2>&1 &
    save_pid frontend $!
    cd "$REPO_ROOT"
    wait_for_port "Frontend" 5173 15
fi

# ── Summary ──────────────────────────────────────────────────

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  All services started!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Frontend${NC}      → ${BOLD}http://localhost:5173${NC}"
echo -e "  ${CYAN}Backend API${NC}   → ${BOLD}http://localhost:8000${NC}"
echo -e "  ${CYAN}Agent API${NC}     → ${BOLD}http://localhost:8001${NC}"
echo -e "  ${CYAN}RAG Service${NC}   → ${BOLD}http://localhost:8002${NC}"
echo -e "  ${CYAN}RQ Worker${NC}     → ${BOLD}Processing hpc_error_logs queue${NC}"
if [ "$SKIP_AIRFLOW" = false ]; then
echo -e "  ${CYAN}Airflow UI${NC}    → ${BOLD}http://localhost:8080${NC}  (airflow / airflow)"
fi
echo ""
echo -e "  Service logs → ${LOG_DIR}/"
echo -e "  Stop all     → ${BOLD}./start.sh --stop${NC}"
echo ""
