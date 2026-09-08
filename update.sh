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
if command -v wget >/dev/null; then
    fetch() { wget -q -O "$2" "$1"; }
elif command -v curl >/dev/null; then
    fetch() { curl -fsSL -o "$2" "$1"; }
else
    c_err "Weder wget noch curl gefunden."; exit 1
fi

work=$(mktemp -d /tmp/puls-src.XXXXXX) || exit 1
trap 'rm -rf "$work"' EXIT

# codeload ist das Ziel, auf das github.com beim Archiv-Download ohnehin
# weiterleitet. Erst direkt dorthin, dann der uebliche Weg als Rueckfallebene —
# je nach Netz und Proxy ist mal der eine, mal der andere erreichbar.
got=""
for url in "https://codeload.github.com/$REPO/zip/refs/heads/$BRANCH" \
           "https://github.com/$REPO/archive/refs/heads/$BRANCH.zip"; do
    c_info "Lade $url"
    if fetch "$url" "$work/puls.zip" && [ -s "$work/puls.zip" ]; then
        got=1; break
    fi
    c_info "Nicht erreichbar, versuche den nächsten Weg …"
done
if [ -z "$got" ]; then
    c_err "Download fehlgeschlagen. Stimmen Repo und Branch?"
    c_err "  Repo:   $REPO"
    c_err "  Branch: $BRANCH"
    c_err "Anderer Branch:  PULS_BRANCH=main ./update.sh"
    exit 1
fi
unzip -q "$work/puls.zip" -d "$work/x" || { c_err "Archiv beschädigt."; exit 1; }

src=$(find "$work/x" -mindepth 1 -maxdepth 1 -type d | head -1)
[ -d "$src/app" ] || { c_err "Im Archiv fehlt der Ordner app/ — falscher Branch?"; exit 1; }

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
