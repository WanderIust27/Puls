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

cd "$work/run" || exit 1
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
