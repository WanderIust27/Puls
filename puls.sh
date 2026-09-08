#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PULS ohne docker compose und ohne Dockge verwalten.
#
# Unraid bringt kein docker compose mit — dieses Skript macht dasselbe mit
# reinen docker-Befehlen. Es liest die .env genauso wie Compose es täte.
#
#   ./puls.sh start     Images bauen und alles starten
#   ./puls.sh stop      alles anhalten
#   ./puls.sh restart   anhalten und neu starten (ohne Neubau)
#   ./puls.sh update    neu bauen und starten (nach einem Update)
#   ./puls.sh logs      Logs aller Container mitlesen
#   ./puls.sh status    Was läuft gerade?
#   ./puls.sh remove    Container entfernen (Daten bleiben erhalten!)
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")"

NETWORK="puls-net"
IMG_APP="puls-coach:latest"
IMG_SCALE="puls-miscale:latest"
C_APP="puls-coach"
C_OLLAMA="puls-ollama"
C_SCALE="puls-miscale"

# --- .env einlesen (Zeilen mit # werden ignoriert) -------------------------
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# Standardwerte, falls die .env fehlt oder etwas nicht gesetzt ist
TZ="${TZ:-Europe/Berlin}"
PULS_PORT="${PULS_PORT:-1337}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct-q4_K_M}"
SYNC_INTERVAL_HOURS="${SYNC_INTERVAL_HOURS:-3}"
PULS_URL="${PULS_URL:-http://localhost:${PULS_PORT}}"
PULS_TOKEN="${PULS_TOKEN:-}"
SCALE_MAC="${SCALE_MAC:-}"
HEIGHT_CM="${HEIGHT_CM:-180}"
AGE="${AGE:-25}"
SEX="${SEX:-male}"
MIN_WEIGHT_KG="${MIN_WEIGHT_KG:-40}"
COOLDOWN_S="${COOLDOWN_S:-300}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Waagen-Container nur starten, wenn der Ordner da ist
WITH_SCALE=1
[ -d ./miscale ] || WITH_SCALE=0

say()  { echo "  $*"; }
section() { echo; echo "=== $* ==="; }

ensure_base() {
    docker network inspect "$NETWORK" >/dev/null 2>&1 || {
        say "Netzwerk $NETWORK anlegen"
        docker network create "$NETWORK" >/dev/null
    }
    for v in puls-data ollama-data; do
        docker volume inspect "$v" >/dev/null 2>&1 || {
            say "Volume $v anlegen"
            docker volume create "$v" >/dev/null
        }
    done
}

build() {
    section "Images bauen"
    say "App … (dauert beim ersten Mal ein paar Minuten)"
    docker build -t "$IMG_APP" .
    if [ "$WITH_SCALE" = "1" ]; then
        say "Waagen-Dienst …"
        docker build -t "$IMG_SCALE" ./miscale
    fi
}

remove_containers() {
    for c in "$C_APP" "$C_OLLAMA" "$C_SCALE"; do
        if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
            docker rm -f "$c" >/dev/null 2>&1 || true
            say "$c entfernt"
        fi
    done
}

start() {
    ensure_base
    section "Container starten"

    docker run -d --name "$C_OLLAMA" \
        --network "$NETWORK" \
        --restart unless-stopped \
        -e OLLAMA_MAX_LOADED_MODELS=1 \
        -e OLLAMA_KEEP_ALIVE=30m \
        -e OLLAMA_NUM_PARALLEL=1 \
        -v ollama-data:/root/.ollama \
        ollama/ollama:latest >/dev/null
    say "$C_OLLAMA läuft"

    docker run -d --name "$C_APP" \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p "${PULS_PORT}:8000" \
        -e "TZ=$TZ" \
        -e "OLLAMA_URL=http://${C_OLLAMA}:11434" \
        -e "OLLAMA_MODEL=$OLLAMA_MODEL" \
        -e "SYNC_INTERVAL_HOURS=$SYNC_INTERVAL_HOURS" \
        -v puls-data:/data \
        "$IMG_APP" >/dev/null
    say "$C_APP läuft auf Port $PULS_PORT"

    if [ "$WITH_SCALE" = "1" ]; then
        if [ -z "$PULS_TOKEN" ]; then
            say "Hinweis: PULS_TOKEN ist leer — der Waagen-Dienst wird von PULS"
            say "         abgewiesen. Token in der App unter Mehr -> Waage holen,"
            say "         in die .env eintragen, dann: ./puls.sh restart"
        fi
        # Host-Netzwerk und privilegiert, weil Bluetooth direkten Zugriff braucht
        docker run -d --name "$C_SCALE" \
            --network host \
            --privileged \
            --restart unless-stopped \
            -e "TZ=$TZ" \
            -e "PULS_URL=$PULS_URL" \
            -e "PULS_TOKEN=$PULS_TOKEN" \
            -e "SCALE_MAC=$SCALE_MAC" \
            -e "HEIGHT_CM=$HEIGHT_CM" \
            -e "AGE=$AGE" \
            -e "SEX=$SEX" \
            -e "MIN_WEIGHT_KG=$MIN_WEIGHT_KG" \
            -e "COOLDOWN_S=$COOLDOWN_S" \
            -e "LOG_LEVEL=$LOG_LEVEL" \
            "$IMG_SCALE" >/dev/null
        say "$C_SCALE läuft"
    fi

    local ip=""
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')" || true
    [ -n "$ip" ] || ip="$(hostname -i 2>/dev/null | awk '{print $1}')" || true
    echo
    say "Fertig. PULS läuft unter  http://${ip:-DEINE-SERVER-IP}:${PULS_PORT}"
    say "Beim ersten Start lädt Ollama das Modell (~4,7 GB) — das dauert."
    say "Fortschritt mitlesen:  ./puls.sh logs"
}

status() {
    section "Status"
    docker ps -a --filter "name=puls-" \
        --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    echo
    if curl -sf "http://localhost:${PULS_PORT}/api/health" >/dev/null 2>&1; then
        say "PULS antwortet auf Port $PULS_PORT."
        curl -s "http://localhost:${PULS_PORT}/api/health"; echo
    else
        say "PULS antwortet auf Port $PULS_PORT noch nicht."
    fi
}

case "${1:-start}" in
    start)
        remove_containers
        build
        start
        ;;
    update)
        section "Update"
        remove_containers
        build
        start
        ;;
    restart)
        remove_containers
        start
        ;;
    stop)
        section "Anhalten"
        for c in "$C_APP" "$C_SCALE" "$C_OLLAMA"; do
            docker stop "$c" >/dev/null 2>&1 && say "$c angehalten" || true
        done
        ;;
    remove)
        section "Container entfernen (Volumes bleiben!)"
        remove_containers
        say "Deine Daten in puls-data und ollama-data sind unangetastet."
        ;;
    logs)
        docker logs -f --tail 60 "${2:-$C_APP}"
        ;;
    status)
        status
        ;;
    *)
        sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
