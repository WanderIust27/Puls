#!/bin/sh
# Prueft, dass update.sh nichts vergisst.
#
# Anlass: Die Wissensdatenbank kam mit dem Archiv herunter, stand aber nicht in
# der Liste der Dateien, die update.sh ins Zielverzeichnis kopiert. Das Ergebnis
# waere nach jedem Update ein leerer Ordner knowledge/ gewesen — und ein leerer
# Bind-Mount schiebt sich ueber die Dateien im Image. Die Wissensdatenbank
# haette geschwiegen, ohne dass irgendwo ein Fehler erscheint.
#
# Aufruf:  ./tests/test_update.sh
cd "$(dirname "$0")/.." || exit 1

fail=0
say() { printf '%s %s\n' "$1" "$2"; }

# Die Liste aus update.sh herausloesen: alles zwischen "for item in" und "; do".
liste=$(sed -n '/^for item in/,/; do/p' update.sh \
        | tr '\n' ' ' | sed 's/^for item in//; s/; do.*//; s/\\//g')

if [ -z "$liste" ]; then
    say "FAIL" "In update.sh ist keine Dateiliste zu finden"
    exit 1
fi
say "OK  " "Dateiliste gefunden: $(echo "$liste" | wc -w) Einträge"

# Jeder Ordner und jede Datei, die im Repository oben liegt und zum Betrieb
# gehoert, muss darin vorkommen. Was hier fehlt, fehlt nach dem Update.
for item in app knowledge miscale tests Dockerfile docker-compose.yml \
            requirements.txt README.md .env.example deploy.sh puls.sh \
            update.sh .gitignore; do
    [ -e "$item" ] || continue
    if echo " $liste " | grep -q " $item "; then
        say "OK  " "wird kopiert: $item"
    else
        say "FAIL" "update.sh vergisst: $item"
        fail=1
    fi
done

# Und umgekehrt: Nichts in der Liste, das es gar nicht gibt — sonst sieht die
# Liste vollstaendig aus und ist es nicht.
for item in $liste; do
    if [ ! -e "$item" ]; then
        say "FAIL" "update.sh nennt $item, das Repository kennt es nicht"
        fail=1
    fi
done

# Die .env darf nie im Paket stehen: Sie enthaelt Token und persoenliche Werte
# und wuerde beim Update ueberschrieben.
if echo " $liste " | grep -q " .env "; then
    say "FAIL" "update.sh würde die .env überschreiben"
    fail=1
else
    say "OK  " "Die .env bleibt unangetastet"
fi

echo
if [ $fail -ne 0 ]; then
    echo "update.sh ist unvollständig."
    exit 1
fi
echo "update.sh kopiert alles Nötige."
