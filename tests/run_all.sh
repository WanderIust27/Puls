#!/bin/sh
# Alle Tests von PULS. Aufruf aus dem Projektordner:  ./tests/run_all.sh
# Legt Wegwerf-Datenbanken an und fasst deine echten Daten nicht an.
set -e
cd "$(dirname "$0")/.."

echo "== Waagen-Parser =="        && (cd miscale && python3 test_parser.py | tail -1)
echo "== Körperdaten =="          && python3 tests/test_body.py | tail -1
echo "== Detaildaten =="          && python3 tests/test_activity_details.py | tail -1
echo "== Garmin-Sync =="          && python3 tests/test_garmin_sync.py | tail -1
echo "== API =="                  && python3 tests/test_api.py | tail -1
echo
echo "Alles bestanden."
