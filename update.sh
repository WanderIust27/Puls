#!/bin/sh
# PULS aktualisieren: neuen Stand von GitHub holen und neu starten.
#
#   ./update.sh              aktualisieren und deployen
#   ./update.sh --no-deploy  nur die Dateien austauschen
#
# Angefasst werden ausschliesslich die Programmdateien. Deine .env bleibt
# stehen (sie liegt nicht im Paket), und die Volumes puls-data und ollama-data
# — also Trainings, Uebungen, Garmin-Tokens und das KI-Modell — ruehrt das
# Skript nicht an.

REPO="${PULS_REPO:-WanderIust27/Puls}"
BRANCH="${PULS_BRANCH:-main}"

# Das Skript ueberschreibt sich beim Kopieren selbst. Die Shell liest ihre
# Datei aber waehrend der Ausfuehrung weiter nach — deshalb zuerst nach /tmp
# ausweichen und von dort arbeiten.
if [ "${PULS_RELOCATED:-}" != "1" ]; then
    tmp_self=$(mktemp /tmp/puls-update.XXXXXX) || exit 1
    cat "$0" > "$tmp_self" && chmod +x "$tmp_self" || exit 1
    PULS_RELOCATED=1 PULS_TARGET="$(pwd)" export PULS_RELOCATED PULS_TARGET
    "$tmp_self" "$@"
    status=$?
    rm -f "$tmp_self"
    exit $status
fi

cd "$PULS_TARGET" || exit 1

c_ok()   { printf '\033[32m  ✓\033[0m %s\n' "$1"; }
c_info() { printf '\033[36m  →\033[0m %s\n' "$1"; }
c_err()  { printf '\033[31m  ✗\033[0m %s\n' "$1" >&2; }

echo
c_info "Aktualisiere PULS in $PULS_TARGET"
c_info "Quelle: $REPO ($BRANCH)"

command -v unzip >/dev/null || { c_err "unzip nicht gefunden."; exit 1; }

work=$(mktemp -d /tmp/puls-src.XXXXXX) || exit 1
trap 'rm -rf "$work"' EXIT

# Bei einem privaten Repository antwortet GitHub ohne Anmeldung mit 404 —
# ununterscheidbar von "gibt es nicht". Deshalb wird ein Token mitgeschickt,
# sobald eines vorliegt, und die Fehlermeldung unten sagt genau das.
#
# Token anlegen: github.com → Settings → Developer settings →
# Personal access tokens → Fine-grained tokens, Zugriff nur auf dieses
# Repository, Berechtigung "Contents: Read-only". Dann in die .env:
#   GITHUB_TOKEN=github_pat_...
TOKEN="${GITHUB_TOKEN:-${PULS_GITHUB_TOKEN:-}}"

if command -v wget >/dev/null; then
    fetch() {
        if [ -n "$TOKEN" ]; then
            wget -q --header="Authorization: Bearer $TOKEN" -O "$2" "$1"
        else
            wget -q -O "$2" "$1"
        fi
    }
elif command -v curl >/dev/null; then
    fetch() {
        if [ -n "$TOKEN" ]; then
            curl -fsSL -H "Authorization: Bearer $TOKEN" -o "$2" "$1"
        else
            curl -fsSL -o "$2" "$1"
        fi
    }
else
    c_err "Weder wget noch curl gefunden."; exit 1
fi

[ -n "$TOKEN" ] && c_ok "Token aus der .env wird verwendet" \
    || c_info "Kein GITHUB_TOKEN gesetzt — das geht nur bei einem öffentlichen Repository."

got=""
for url in "https://api.github.com/repos/$REPO/zipball/$BRANCH" \
           "https://codeload.github.com/$REPO/zip/refs/heads/$BRANCH" \
           "https://github.com/$REPO/archive/refs/heads/$BRANCH.zip"; do
    c_info "Lade $(echo "$url" | cut -c1-60)…"
    if fetch "$url" "$work/puls.zip" && [ -s "$work/puls.zip" ] \
       && unzip -tq "$work/puls.zip" >/dev/null 2>&1; then
        got=1; break
    fi
    c_info "Nicht erreichbar, versuche den nächsten Weg …"
done

if [ -z "$got" ]; then
    echo
    c_err "Download fehlgeschlagen."
    if [ -z "$TOKEN" ]; then
        c_err "Es ist kein GITHUB_TOKEN gesetzt. Bei einem privaten Repository"
        c_err "antwortet GitHub dann mit 404 — genau das ist hier passiert."
        c_err ""
        c_err "Zwei Wege:"
        c_err "  1. Token anlegen (github.com → Settings → Developer settings →"
        c_err "     Personal access tokens → Fine-grained, nur dieses Repo,"
        c_err "     Contents: Read-only) und in die .env eintragen:"
        c_err "         GITHUB_TOKEN=github_pat_..."
        c_err "  2. Oder das Repository öffentlich schalten."
    else
        c_err "Das Token wurde mitgeschickt, GitHub hat trotzdem abgelehnt."
        c_err "Prüfen: Ist es abgelaufen? Hat es Zugriff auf $REPO?"
        c_err "Test:  curl -I -H \"Authorization: Bearer \$GITHUB_TOKEN\" \\"
        c_err "         https://api.github.com/repos/$REPO"
    fi
    c_err ""
    c_err "Repo: $REPO   Branch: $BRANCH"
    exit 1
fi

unzip -q "$work/puls.zip" -d "$work/x" || { c_err "Archiv beschädigt."; exit 1; }

# Der Ordnername im Archiv haengt vom Weg ab: GitHub nennt ihn nach Repo und
# Branch, die API nach Repo und Commit. Deshalb wird der einzige Unterordner
# gesucht statt ein Name geraten — und geprueft, dass app/ wirklich drin ist.
src=$(find "$work/x" -mindepth 1 -maxdepth 1 -type d | head -1)
if [ -z "$src" ] || [ ! -d "$src/app" ]; then
    c_err "Im Archiv fehlt der Ordner app/ — falscher Branch oder leeres Paket?"
    c_err "Entpackt nach: ${src:-<nichts gefunden>}"
    exit 1
fi
c_ok "Paket entpackt ($(find "$src" -type f | wc -l) Dateien)"

# Datenbank sichern, solange sie noch unberuehrt ist. Kostet Sekunden und
# erspart im Zweifel den Abend.
if docker volume inspect puls-data >/dev/null 2>&1; then
    stamp=$(date +%Y%m%d-%H%M)
    if docker run --rm -v puls-data:/data -v "$PULS_TARGET":/backup alpine \
         sh -c 'cp /data/puls.db /backup/puls-backup-'"$stamp"'.db' 2>/dev/null; then
        c_ok "Datenbank gesichert: puls-backup-$stamp.db"
    fi
fi

# Nur die Programmdateien ersetzen. Alles andere im Ordner bleibt liegen.
for item in app miscale tests Dockerfile docker-compose.yml requirements.txt \
            README.md .env.example deploy.sh puls.sh update.sh .gitignore; do
    [ -e "$src/$item" ] || continue
    rm -rf "./$item"
    cp -R "$src/$item" "./$item"
done
chmod +x deploy.sh puls.sh update.sh 2>/dev/null
[ -f miscale/entrypoint.sh ] && chmod +x miscale/entrypoint.sh
[ -f tests/run_all.sh ] && chmod +x tests/run_all.sh
c_ok "Programmdateien aktualisiert"

if [ ! -f .env ]; then
    cp .env.example .env
    c_ok ".env aus der Vorlage angelegt — bitte durchsehen"
fi

if [ "${1:-}" = "--no-deploy" ]; then
    c_info "Ohne Deploy beendet. Weiter mit:  ./deploy.sh"
    exit 0
fi

echo
exec ./deploy.sh
