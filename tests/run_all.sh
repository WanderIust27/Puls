#!/bin/sh
# Alle Tests von PULS. Aufruf aus dem Projektordner:  ./tests/run_all.sh
# Legt Wegwerf-Datenbanken an und fasst deine echten Daten nicht an.
#
# Kein "| tail" um die Aufrufe: in einer Pipe zaehlt der Exit-Code des letzten
# Glieds, ein abgestuerzter Test bliebe damit unbemerkt.
cd "$(dirname "$0")/.." || exit 1

failed=""
run() {
    name="$1"; shift
    out=$("$@" 2>&1)
    if [ $? -eq 0 ]; then
        printf '  %-22s %s\n' "$name" "$(echo "$out" | tail -1)"
    else
        printf '  %-22s FEHLGESCHLAGEN\n' "$name"
        echo "$out" | sed 's/^/      /'
        failed="$failed $name"
    fi
}

echo "PULS — Testlauf"
(cd miscale && python3 test_parser.py >/dev/null 2>&1) \
    && printf '  %-22s %s\n' "Waagen-Parser" "bestanden" \
    || { printf '  %-22s FEHLGESCHLAGEN\n' "Waagen-Parser"; failed="$failed Waagen-Parser"; }
run "Körperdaten"     python3 tests/test_body.py
run "Detaildaten"     python3 tests/test_activity_details.py
run "Gym-Auswertung"  python3 tests/test_gym_analysis.py
run "Gemüt & Supplements" python3 tests/test_mood.py
run "Lernen & Gedächtnis" python3 tests/test_learning.py
run "Zusammenhänge"    python3 tests/test_insights.py
run "Coach-Vorschläge" python3 tests/test_suggestions.py
run "Statistik & Autopilot" python3 tests/test_stats.py
run "Workout an die Uhr" python3 tests/test_workout_push.py
run "Garmin-Sync"     python3 tests/test_garmin_sync.py
run "API"             python3 tests/test_api.py
run "Frontend"        python3 tests/test_frontend.py
run "Invarianten"     python3 tests/test_invariants.py
run "Deploy-Skript"   sh tests/test_deploy.sh

echo
if [ -n "$failed" ]; then
    echo "Fehlgeschlagen:$failed"
    exit 1
fi
echo "Alles bestanden."
