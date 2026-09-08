#!/usr/bin/env bash
# PULS ohne Docker Compose und ohne Dockge aufsetzen.
#
# Unraid bringt kein "docker compose" mit. Dieses Skript macht dasselbe, was die
# docker-compose.yml beschreibt — nur mit reinen docker-Befehlen. Es ist gefahrlos
# wiederholbar: bestehende Container werden ersetzt, die Daten-Volumes nie angefasst.
#
#   ./deploy.sh              Images bauen und alles starten  (Standard)
#   ./deploy.sh --no-build   nur neu starten, ohne zu bauen
#   ./deploy.sh stop         alle Container anhalten und entfernen
#   ./deploy.sh logs         Logs aller drei Container verfolgen
#   ./deploy.sh status       Kurzüberblick
#
# Die Daten liegen in den Volumes puls-data und ollama-data und überleben alles
# außer einem ausdrücklichen "docker volume rm".

set -euo pipefail
cd "$(dirname "$0")"

NET=puls-net
IMG_APP=puls-coach:latest
IMG_SCALE=puls-miscale:latest

c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m•\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------- Einstellungen
if [ -f .env ]; then
    set -a; . ./.env; set +a
    c_ok "Einstellungen aus .env geladen"
else
    c_warn "Keine .env gefunden — es gelten die Standardwerte."
    c_warn "Anlegen mit:  cp .env.example .env"
fi

TZ="${TZ:-Europe/Berlin}"
PULS_PORT="${PULS_PORT:-1337}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
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

# Bluetooth-Container nur bauen und starten, wenn der Ordner da ist
WANT_SCALE=1
[ -d ./miscale ] || WANT_SCALE=0

# ------------------------------------------------------------------- Unterbefehle
cmd="${1:-deploy}"

case "$cmd" in
  stop)
      for c in puls-miscale puls-coach puls-ollama; do
          docker rm -f "$c" >/dev/null 2>&1 && c_ok "$c entfernt" || true
      done
      echo
      c_info "Die Volumes puls-data und ollama-data sind unberührt."
      exit 0 ;;
  logs)
      exec docker logs -f --tail 50 puls-coach ;;
  status)
      docker ps --filter "name=puls-" \
          --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
      echo
      curl -fsS "http://localhost:${PULS_PORT}/api/health" 2>/dev/null \
          && echo || c_warn "PULS antwortet noch nicht auf Port ${PULS_PORT}."
      exit 0 ;;
  deploy|--no-build) : ;;
  *) c_err "Unbekannter Befehl: $cmd"; exit 1 ;;
esac

# ------------------------------------------------------------------ Vorbedingungen
command -v docker >/dev/null || { c_err "docker nicht gefunden."; exit 1; }

echo
c_info "Netzwerk und Volumes vorbereiten …"
docker network create "$NET" >/dev/null 2>&1 && c_ok "Netzwerk $NET angelegt" \
    || c_ok "Netzwerk $NET vorhanden"
for v in puls-data ollama-data; do
    docker volume create "$v" >/dev/null && c_ok "Volume $v bereit"
done

# ------------------------------------------------------------------------- Bauen
if [ "$cmd" != "--no-build" ]; then
    echo
    c_info "Image für die App bauen (dauert beim ersten Mal ein paar Minuten) …"
    docker build -t "$IMG_APP" . || { c_err "Build der App fehlgeschlagen."; exit 1; }
    c_ok "$IMG_APP gebaut"

    if [ "$WANT_SCALE" = 1 ]; then
        c_info "Image für die Bluetooth-Brücke bauen …"
        if docker build -t "$IMG_SCALE" ./miscale; then
            c_ok "$IMG_SCALE gebaut"
        else
            c_warn "Bluetooth-Brücke ließ sich nicht bauen — wird übersprungen."
            WANT_SCALE=0
        fi
    fi
fi

# -------------------------------------------------------------------- Ollama
echo
c_info "Ollama starten …"
docker rm -f puls-ollama >/dev/null 2>&1 || true
docker pull ollama/ollama:latest >/dev/null 2>&1 || c_warn "Konnte Ollama-Image nicht aktualisieren, nutze vorhandenes."
docker run -d \
    --name puls-ollama \
    --network "$NET" \
    --restart unless-stopped \
    -e OLLAMA_MAX_LOADED_MODELS=1 \
    -e OLLAMA_KEEP_ALIVE=30m \
    -e OLLAMA_NUM_PARALLEL=1 \
    -v ollama-data:/root/.ollama \
    ollama/ollama:latest >/dev/null
c_ok "puls-ollama läuft (nur CPU, GPU bleibt frei)"

# ----------------------------------------------------------------------- App
echo
c_info "PULS starten …"
docker rm -f puls-coach >/dev/null 2>&1 || true
docker run -d \
    --name puls-coach \
    --network "$NET" \
    --restart unless-stopped \
    -p "${PULS_PORT}:8000" \
    -e "TZ=${TZ}" \
    -e "OLLAMA_URL=http://puls-ollama:11434" \
    -e "OLLAMA_MODEL=${OLLAMA_MODEL}" \
    -e "SYNC_INTERVAL_HOURS=${SYNC_INTERVAL_HOURS}" \
    -v puls-data:/data \
    "$IMG_APP" >/dev/null
c_ok "puls-coach läuft auf Port ${PULS_PORT}"

# ------------------------------------------------------------ Bluetooth-Brücke
if [ "$WANT_SCALE" = 1 ]; then
    echo
    c_info "Bluetooth-Brücke starten …"
    docker rm -f puls-miscale >/dev/null 2>&1 || true
    if [ -z "$PULS_TOKEN" ]; then
        c_warn "PULS_TOKEN ist leer — die Brücke startet, PULS lehnt Messungen aber ab."
        c_warn "Token holen unter Mehr → Waage, in die .env eintragen, Skript nochmal starten."
    fi
    docker run -d \
        --name puls-miscale \
        --network host \
        --privileged \
        --restart unless-stopped \
        -e "TZ=${TZ}" \
        -e "PULS_URL=${PULS_URL}" \
        -e "PULS_TOKEN=${PULS_TOKEN}" \
        -e "SCALE_MAC=${SCALE_MAC}" \
        -e "HEIGHT_CM=${HEIGHT_CM}" \
        -e "AGE=${AGE}" \
        -e "SEX=${SEX}" \
        -e "MIN_WEIGHT_KG=${MIN_WEIGHT_KG}" \
        -e "COOLDOWN_S=${COOLDOWN_S}" \
        -e "LOG_LEVEL=${LOG_LEVEL}" \
        "$IMG_SCALE" >/dev/null
    c_ok "puls-miscale läuft"
fi

# ------------------------------------------------------------------- Abschluss
echo
c_info "Warte auf PULS …"
for i in $(seq 1 30); do
    if curl -fsS "http://localhost:${PULS_PORT}/api/health" >/dev/null 2>&1; then
        c_ok "PULS antwortet."
        break
    fi
    sleep 2
    [ "$i" = 30 ] && c_warn "PULS antwortet noch nicht — schau in die Logs: ./deploy.sh logs"
done

IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')"
echo
echo "──────────────────────────────────────────────"
echo "  PULS läuft:  http://${IP:-DEINE-SERVER-IP}:${PULS_PORT}"
echo "──────────────────────────────────────────────"
echo
echo "  Logs ansehen:     ./deploy.sh logs"
echo "  Status prüfen:    ./deploy.sh status"
echo "  Alles anhalten:   ./deploy.sh stop"
echo "  Nach einem Update: ./deploy.sh  (baut neu und startet durch)"
echo
if docker exec puls-ollama ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL%%:*}"; then
    c_ok "KI-Modell ${OLLAMA_MODEL} ist geladen."
else
    c_info "Das KI-Modell (~4,7 GB) wird beim ersten Aufruf des Coaches geladen."
    c_info "Vorab holen geht mit:  docker exec puls-ollama ollama pull ${OLLAMA_MODEL}"
fi
