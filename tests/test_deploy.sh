#!/bin/sh
# Prueft, dass deploy.sh bis zum Ende durchlaeuft.
#
# Anlass: Eine Zeile der Form  [ Bedingung ] && Aktion  liefert unter
# "set -e" den Exit-Code 1, wenn die Bedingung nicht zutrifft — und beendet
# das Skript. So brach der Deploy nach dem Ollama-Schritt ab, ohne die App
# neu zu starten, und meldete dabei nicht einmal einen Fehler.
#
# Docker wird durch eine Attrappe ersetzt; geprueft wird nur der Ablauf.
# Aufruf:  ./tests/test_deploy.sh
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/bin" "$work/run"
cp deploy.sh "$work/run/"
cp -r app miscale Dockerfile requirements.txt "$work/run/" 2>/dev/null
printf 'PULS_PORT=1337\nOLLAMA_GPU=all\n' > "$work/run/.env"

# --- Docker-Attrappe: bestaetigt alles, ohne etwas zu tun ---------------
cat > "$work/bin/docker" <<'STUB'
#!/bin/sh
# Mitschreiben, womit gestartet wird — sonst prueft der Test nur, dass das
# Skript durchlaeuft, und nicht, ob der Container die richtigen Mounts bekommt.
echo "$@" >> "$DOCKER_LOG"
case "$1" in
  info)    echo " Runtimes: io.containerd.runc.v2 nvidia runc" ;;
  exec)    exit 0 ;;                 # Karte im Container sichtbar
  logs)    echo "kein passender Eintrag" ;;   # KEINE "inference compute"-Zeile
  ps)      echo "NAMES STATUS" ;;
  build|run|rm|pull|network|volume|restart|stop) exit 0 ;;
  *)       exit 0 ;;
esac
STUB
chmod +x "$work/bin/docker"

# curl-Attrappe: die Wartschleife soll sofort Erfolg melden
cat > "$work/bin/curl" <<'STUB'
#!/bin/sh
echo '{"app":"ok","version":"testtest01"}'
STUB
chmod +x "$work/bin/curl"

# Die Wissensdatenbank gehoert zum Paket — ohne sie prueft der Test den
# interessanten Fall nicht.
mkdir -p "$work/run/knowledge"
cp "$ROOT"/knowledge/*.md "$work/run/knowledge/" 2>/dev/null

cd "$work/run" || exit 1
DOCKER_LOG="$work/docker.log"
export DOCKER_LOG
: > "$DOCKER_LOG"
out=$(PATH="$work/bin:$PATH" bash ./deploy.sh 2>&1)
status=$?

fail=0
say() { printf '%s %s\n' "$1" "$2"; }

if [ $status -eq 0 ]; then
    say "OK  " "deploy.sh läuft vollständig durch (Exit $status)"
else
    say "FAIL" "deploy.sh bricht mit Exit $status ab"
    echo "$out" | tail -8 | sed 's/^/      /'
    fail=1
fi

# Der entscheidende Punkt: Nach Ollama muss die App noch drankommen.
# Muster genau genug wählen: "App" allein trifft auch
# "Image für die App bauen" und würde einen Abbruch danach verdecken.
for needle in "Ollama starten" "PULS starten" "Bluetooth-Brücke starten" \
              "PULS läuft:"; do
    if echo "$out" | grep -qi "$needle"; then
        say "OK  " "Schritt erreicht: $needle"
    else
        say "FAIL" "Schritt fehlt: $needle — Skript bricht vorher ab"
        fail=1
    fi
done

# Die Wissensdatenbank muss auch wirklich im Container ankommen. deploy.sh
# benutzt kein docker compose, sondern baut den Stack mit einzelnen
# docker-Befehlen nach — eine Aenderung an der docker-compose.yml erreicht
# den Server also gar nicht. Genau das war hier schon einmal der Fall.
run_line=$(grep -E '^run -d|^run  *-d' "$DOCKER_LOG" | grep -- "--name puls-coach")
for needle in "-v puls-data:/data" "-v puls-models:/models"               "/knowledge:ro" "PULS_EMBED"; do
    if echo "$run_line" | grep -q -- "$needle"; then
        say "OK  " "Container bekommt: $needle"
    else
        say "FAIL" "Container bekommt NICHT: $needle"
        fail=1
    fi
done

if grep -q "volume create puls-models" "$DOCKER_LOG"; then
    say "OK  " "Modell-Cache wird angelegt"
else
    say "FAIL" "Volume puls-models fehlt — das Modell lädt bei jedem Start neu"
    fail=1
fi

# Ein leerer Wissensordner darf nicht eingehaengt werden: Der Mount schoebe
# sich sonst ueber die Dateien im Image, und die Datenbank bliebe still leer.
rm -f "$work/run/knowledge"/*.md
: > "$DOCKER_LOG"
PATH="$work/bin:$PATH" bash ./deploy.sh >/dev/null 2>&1
if grep -E '^run -d' "$DOCKER_LOG" | grep -- "--name puls-coach"    | grep -q -- "/knowledge:ro"; then
    say "FAIL" "Leerer Wissensordner wird trotzdem eingehängt"
    fail=1
else
    say "OK  " "Leerer Wissensordner wird übersprungen"
fi
cp "$ROOT"/knowledge/*.md "$work/run/knowledge/" 2>/dev/null

# Und das ohne "inference compute"-Zeile im Log, genau der Fall von damals
if echo "$out" | grep -q "Grafikkarte"; then
    say "OK  " "GPU-Prüfung meldet sich, ohne den Ablauf zu beenden"
else
    say "FAIL" "GPU-Prüfung fehlt"
    fail=1
fi

echo
if [ $fail -ne 0 ]; then
    echo "deploy.sh-Test fehlgeschlagen."
    exit 1
fi
echo "deploy.sh läuft durch."
