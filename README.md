# PULS — dein lokaler Trainingscoach

Selbstgehosteter Trainingscoach mit lokaler KI (Ollama, rein auf CPU), Garmin-Anbindung
in beide Richtungen, Übungsbibliothek mit automatischer Progression und einem dunklen,
motivierenden Dashboard. Läuft komplett auf deinem Server — keine Cloud-KI, keine Abos.

## Deine Wochenstruktur

PULS plant genau so, wie du trainierst:

| Wann | Was |
|---|---|
| Jeden Morgen | 20–30 min Laufen — meist locker, ein Tempo- und ein langer Lauf pro Woche |
| Mo / Mi / Fr abends | Gym 60–90 min: Kettlebell-Auftakt → Klimmzug-Arbeit → Maschinen → Dehnen |
| Jeden Abend | Kurze Yoga-/Dehneinheit vor dem Schlafen |

Alles davon ist unter *Mehr → Wochenstruktur* umstellbar. Ein Klick auf **Woche planen**
erzeugt die komplette Woche; **Alles an Garmin** schiebt sie auf die Fenix.

## Die zwei Hauptziele

- **10 km unter 60 Minuten** — der Benchmark-Lauf kalibriert deine Trainingstempi, das
  Dashboard zeigt die aktuelle Prognose und wie weit du noch weg bist.
- **Mehr Klimmzüge** — eigener Block in jeder Gym-Einheit. Je nach Maximum arbeitet PULS
  mit negativen, bandunterstützten oder freien Klimmzügen.

## Wie die Progression funktioniert

Die Zahlen rechnet Code, nicht die KI — das Modell wählt aus und erklärt, aber es erfindet
keine Gewichte. Verwendet wird **doppelte Progression**:

1. Alle Sätze auf Zielwiederholungen geschafft, Ziel ist am oberen Ende der Spanne?
   → Gewicht eine Stufe hoch, Wiederholungen zurück auf den unteren Wert.
2. Alle Sätze geschafft, aber noch Luft? → eine Wiederholung mehr (bei „war leicht" zwei).
3. Zweimal in Folge deutlich verfehlt? → Deload, eine Stufe runter.
4. Sonst: gleiche Vorgabe nochmal.

Die Schrittweite hängt am Gerät: Maschine 5 kg, Kabel/Band 2,5 kg, Kurzhantel 2 kg,
Kettlebell 4 kg — pro Übung einstellbar.

**Der Clou:** Die Fenix 7 protokolliert bei Kraft-Workouts jeden Satz mit Wiederholungen
und Gewicht. PULS holt diese Sätze beim Sync zurück, ordnet sie deinen Übungen zu und
rechnet die Progression von selbst weiter. Du musst nichts doppelt eintragen.

## Was der Coach aus deinen Läufen liest

Nach jedem Sync holt PULS zu jeder Laufeinheit die Kennzahlen von der Uhr und
bewertet sie. Tippe in der Übungen-Ansicht auf einen Lauf, um die Analyse zu öffnen.

Ausgelesen werden Distanz, Zeit, Tempo, Puls und die Zeit je Herzfrequenzzone,
Schrittfrequenz und Schrittlänge, Höhenmeter und Trainingseffekt. Bodenkontaktzeit
und vertikale Bewegung nur, wenn ein Brustgurt (HRM-Pro) oder RD-Pod mitläuft — die
Fenix allein misst sie nicht.

Bewertet wird dann:

- **Tempo gegen deine kalibrierten Zonen.** Der häufigste Fehler im Breitensport ist,
  die lockeren Läufe zu schnell zu laufen. PULS sagt es dir.
- **Pulsverteilung.** Bei einem Grundlagenlauf sollen 75 % und mehr in Zone 1–2 liegen;
  bei einer Tempoeinheit ist Zone 4 dagegen genau das Ziel. Die Bewertung weiß, welche
  Art Einheit gemeint war, und misst entsprechend.
- **Schrittfrequenz.** Unter 160 Schritten pro Minute folgt ein konkreter Hinweis.
- **Ermüdung im Verlauf.** Steigt dein Puls auf der zweiten Hälfte bei gleichem Tempo
  deutlich an, war die Einheit zu lang oder zu schnell (aerobe Entkopplung).
- **Fortschritt.** Schneller bei gleichem Puls als im Schnitt der letzten Wochen — das
  ist der Vergleich, auf den es ankommt.

## Yoga-Stellungen

Die Abendeinheit geht als echtes Yoga-Workout auf die Uhr: Jede Stellung wird mit
Garmins Übungsnamen übergeben, die Fenix zeigt also Namen und Abbildung statt eines
namenlosen Zeitblocks. Der Kurzhinweis („Knie locker sinken lassen") steht als
Beschreibung dabei.

Die ausführliche Anleitung — wie du Schritt für Schritt in jede Stellung kommst,
worauf sie wirkt und wie sie auf Sanskrit heißt — findest du in der App unter
*Plan → Yoga-Stellungen*. Einmal in Ruhe durchgehen, dann brauchst du sie abends nicht
mehr.

## Kalibrierung (Benchmark)

Unter *Plan → Kalibrierung*:

- **Benchmark-Lauf (Cooper-Test)**: 12 Minuten so weit wie möglich. Daraus berechnet PULS
  VO₂max, deine vier Trainingstempi und eine ehrliche 10-km-Prognose. Die Rechnung folgt
  dem Modell von Jack Daniels — die Werte decken sich mit dessen VDOT-Tabellen.
- **Kraft-Test**: pro Übung ein Satz bis zum sauberen Maximum. Daraus 1RM nach Epley und
  neue Arbeitsgewichte (mit 5 % Sicherheitsabschlag).
- **Klimmzug-Maximum**: bestimmt, mit welcher Variante weitergearbeitet wird.

PULS erinnert alle 10 Wochen ans Nachkalibrieren.


## Installieren und aktualisieren — ein Befehl

```bash
cd /mnt/user/appdata/puls-coach && \
  wget -qO update.sh https://codeload.github.com/WanderIust27/Puls/raw/claude/upload-zip-files-git-h41xf4/update.sh && \
  chmod +x update.sh && ./update.sh
```

Danach genügt jedes Mal:

```bash
cd /mnt/user/appdata/puls-coach && ./update.sh
```

Das Skript lädt den aktuellen Stand, sichert vorher die Datenbank als
`puls-backup-<Datum>.db` in den Ordner, tauscht nur die Programmdateien aus und
startet über `deploy.sh` neu. Deine `.env` bleibt stehen, die Volumes
`puls-data` und `ollama-data` werden nicht angefasst.

| Aufruf | Wirkung |
|---|---|
| `./update.sh` | holen, austauschen, deployen |
| `./update.sh --no-deploy` | nur die Dateien austauschen |
| `PULS_BRANCH=main ./update.sh` | einen anderen Branch nehmen |

## System aktualisieren (von Hand)

Deine Daten liegen in den Docker-Volumes und deine persönlichen Einstellungen in der
Datei `.env` — beides fasst ein Update nicht an. Es genügt, die Programmdateien zu
ersetzen und neu zu bauen.

### Wo liegt mein Ordner?

```bash
ls -d /mnt/user/appdata/puls-coach /mnt/user/appdata/dockge/stacks/puls-coach 2>/dev/null
```

Der Pfad, der ausgegeben wird, ist dein Zielordner.

### Dateien übertragen

**Weg A — über den Finder (am bequemsten).** Zip auf dem Mac entpacken, dann im Finder
*Gehe zu → Mit Server verbinden* → `smb://tower` → Share `appdata` öffnen und zum
Zielordner navigieren. Aus dem entpackten Ordner diese Dinge hineinziehen und das
Ersetzen bestätigen:

`app/` · `miscale/` · `Dockerfile` · `docker-compose.yml` · `requirements.txt` ·
`README.md` · `.env.example`

**Weg B — per Terminal vom Mac aus (präziser).** Ein Befehl, der den Inhalt sauber
spiegelt:

```bash
rsync -av --delete-after \
  ~/Downloads/puls-coach/ \
  root@tower:/mnt/user/appdata/puls-coach/
```

Ohne rsync tut es auch:

```bash
scp -r ~/Downloads/puls-coach/* root@tower:/mnt/user/appdata/puls-coach/
```

**Weg C — über die Unraid-Oberfläche.** Der eingebaute Dateimanager (Ordnersymbol oben
rechts in der WebGUI) kann Dateien hochladen — für einzelne Dateien praktisch, für den
ganzen Ordner umständlich.

### Danach

```bash
cd /mnt/user/appdata/puls-coach
./deploy.sh
```

Das Skript baut die geänderten Images neu und startet die Container durch. Wer Compose
oder Dockge nutzt, deployt stattdessen dort.

### Warum nichts verloren geht

| Was | Wo es liegt | Beim Update |
|---|---|---|
| Trainings, Übungen, Progression, Garmin-Tokens | Volume `puls-data` | bleibt |
| KI-Modell (~4,7 GB) | Volume `ollama-data` | bleibt, kein Neu-Download |
| Dein Waagen-Token, Größe, Alter | Datei `.env` | bleibt (nicht im Paket enthalten) |
| Programmcode | Ordner im Stacks-Verzeichnis | wird ersetzt |

Die Volumes sind in der Compose-Datei als `external` eingetragen, damit sie unabhängig
vom Stacknamen immer gleich heißen. Beim Start legt PULS fehlende Tabellen und Spalten
selbst an — einen Migrationsschritt gibt es nicht.

**Erstes Update von einer älteren Version?** Dann einmalig noch:

```bash
cd /mnt/user/appdata/puls-coach
cp .env.example .env          # danach PULS_TOKEN und PULS_PORT eintragen
chmod +x deploy.sh
```

**Wenn etwas klemmt:** `./deploy.sh logs` zeigt, woran es hängt, `./deploy.sh status`
gibt einen Überblick. `./deploy.sh stop` gefolgt von `./deploy.sh` setzt alles neu auf,
ohne die Daten anzurühren — die Volumes werden dabei nie gelöscht.

## Installation ohne Compose und ohne Dockge (empfohlen)

Unraid bringt kein `docker compose` mit, und Dockge legt beim Anlegen eines neuen
Stacks eine nginx-Vorlage an — das führt leicht in die Irre. Am zuverlässigsten läuft
PULS deshalb über das mitgelieferte Skript. Es macht genau das, was die
`docker-compose.yml` beschreibt, aber mit reinen `docker`-Befehlen.

```bash
cd /mnt/user/appdata/puls-coach     # oder wo dein Ordner liegt
cp .env.example .env                # einmalig, danach ausfüllen
chmod +x deploy.sh
./deploy.sh
```

Das Skript legt Netzwerk und Volumes an, baut beide Images, ersetzt laufende Container
und wartet, bis PULS antwortet. Am Ende steht die fertige Adresse im Terminal.

Weitere Befehle:

| Befehl | Wirkung |
|---|---|
| `./deploy.sh` | Images bauen und alles starten — auch nach jedem Update |
| `./deploy.sh --no-build` | nur neu starten, ohne zu bauen |
| `./deploy.sh status` | laufende Container und Erreichbarkeit prüfen |
| `./deploy.sh logs` | Logs verfolgen |
| `./deploy.sh stop` | Container anhalten und entfernen (Daten bleiben) |

Das Skript ist beliebig oft wiederholbar. Es fasst die Volumes `puls-data` und
`ollama-data` nie an — deine Trainings, Übungen und Garmin-Tokens überstehen jeden
Durchlauf.

### Falls du doch Compose willst

Über die Community Apps das Plugin **Compose Manager** installieren, danach ein neues
Terminal öffnen. Dann funktioniert im Projektordner auch:

```bash
docker compose up -d --build
```

Die `docker-compose.yml` liegt bei und ist gleichwertig zum Skript.

### Falls du Dockge benutzen willst

Wichtig: In Dockge **nicht** „+ Compose" drücken — das erzeugt die nginx-Vorlage. Der
Ordner muss stattdessen im Stacks-Verzeichnis liegen (Host-Pfad des Mappings auf
`/opt/stacks`, siehe Dockge-Containereinstellungen), dann erscheint der Stack von
selbst in der Liste und kann deployt werden. Dockge braucht dafür ein funktionierendes
`docker compose` im Hintergrund — fehlt das, nimm das Skript oben.

### KI-Modell wählen

Das Modell stellst du in der App unter *Mehr → KI-Modell* ein — der Download läuft im
Hintergrund mit Fortschrittsanzeige, du musst keine Datei anfassen.

| Modell | RAM | Tempo auf CPU | Wofür |
|---|---|---|---|
| **Qwen 3 · 8B** | ~4,7 GB | gemütlich | Empfohlen. Beste Qualität in dieser Größe, braucht so viel wie das alte 7B-Modell |
| Qwen 3 · 4B | ~2,8 GB | flott | Rund doppelt so schnell, immer noch besser als die Vorgängergeneration |
| Gemma 3 · 4B | ~2,6 GB | flott | Formuliert oft natürlicher |
| Llama 3.2 · 3B | ~2,0 GB | schnell | Der Sparsame |

Die GPU wird bewusst nicht angefasst — sie bleibt für Hermes frei.

### Ersteinrichtung in der App

Kommst du von der alten `docker run`-Installation, räum vorher einmal auf — das Skript
legt die Container ohnehin neu an:

```bash
docker rm -f puls-coach puls-ollama puls-miscale 2>/dev/null
```

Die Volumes bleiben dabei erhalten, deine Daten sind sicher. Dann in der App:

1. *Mehr → Garmin Connect*: verbinden (MFA wird unterstützt, gespeichert werden nur Tokens).
2. *Mehr → Wochenstruktur*: Lauf-/Gym-Tage, Dauer, Ziele prüfen.
3. *Übungen*: deine Maschinen durchgehen — Startgewichte stehen schon drin, anpassen was
   nicht stimmt. Neue Geräte mit „+ Neu"; das passende Garmin-Übungsbild wird automatisch
   zugeordnet.
4. *Plan → Kalibrierung*: Benchmark-Lauf und Kraft-Test erstellen, an die Uhr schicken.
5. *Plan → Woche planen*.

## Mi Scale 2 einbinden

Der Container `puls-miscale` lauscht per Bluetooth passiv auf deine Waage — nichts
koppeln, kein Handy, keine Xiaomi-Cloud. Jede stabile Messung landet automatisch in PULS.

### Was du am Bluetooth-Dongle einstellen musst: nichts

Unraid bringt selbst kein BlueZ mit — deshalb steckt der komplette Bluetooth-Stack
(dbus und bluetoothd) **im Container**. Du musst auf dem Server also nichts
installieren, keine Dienste starten und nichts in die `go`-Datei eintragen. Der
Container startet den Stack selbst, schaltet den Adapter ein und beginnt zu scannen.

Nötig ist nur, dass der Unraid-Kernel den Dongle als Gerät erkennt. Prüf das einmal
per SSH:

```bash
lsusb | grep -i blue          # zeigt den Dongle
ls /sys/class/bluetooth       # sollte hci0 zeigen
```

Zeigt `lsusb` den Dongle, aber `/sys/class/bluetooth` bleibt leer, fehlt der Treiber.
Das betrifft vor allem Realtek-Chips (RTL8761B, verbreitet bei Bluetooth-5.x-Sticks):

```bash
modprobe btusb                # Treiber laden
ls /sys/class/bluetooth       # nochmal prüfen
```

Klappt das, gehört `modprobe btusb` in die Datei `/boot/config/go`, damit es einen
Neustart übersteht. Bleibt es leer, unterstützt dein Kernel den Chip nicht — dann
hilft nur ein anderer Dongle (Intel-Chipsätze wie AX200/AX210 und CSR8510 laufen
erfahrungsgemäß problemlos).

### Einrichtung

1. In PULS unter *Mehr → Waage* das Token kopieren.
2. In der `docker-compose.yml` bei `miscale` als `PULS_TOKEN` einsetzen, dazu
   `HEIGHT_CM`, `AGE` und `SEX` für die Körperfett-Schätzung.
3. Neu starten: `./deploy.sh`
4. In PULS auf *Mehr → Waage* gehen — dort siehst du **live**, was passiert.

### Die Live-Ansicht

Die Seite fragt den Dienst alle drei Sekunden ab und zeigt einen von fünf Zuständen:

| Anzeige | Bedeutung |
|---|---|
| Dienst nicht erreichbar | Container läuft nicht, oder das Token stimmt nicht |
| Kein Bluetooth-Adapter | Dongle steckt nicht, oder der Treiber fehlt (siehe oben) |
| Scan läuft — warte auf die Waage | Alles bereit, aber die Waage funkt noch nicht |
| Waage wird empfangen | Signal kommt an — jetzt draufstellen und stillstehen |
| Alles verbunden | Messungen laufen ein |

Darunter zählen drei Werte mit: empfangene Signale insgesamt, davon von der Waage, und
wie viele Messungen übernommen wurden. Unter „Gefundene Bluetooth-Geräte anzeigen"
stehen alle Geräte in Reichweite mit Signalstärke — deine Waage erscheint dort
hervorgehoben, sobald du drauftrittst. Die Adresse kannst du als `SCALE_MAC`
eintragen, damit nur sie ausgewertet wird.

**Wichtig zum Verständnis:** Die Waage funkt nur, während jemand draufsteht. Ein leerer
Gerätefund heißt also nicht, dass etwas kaputt ist — kurz drauftreten, dann taucht sie
auf. Zur Fehlersuche hilft `LOG_LEVEL=DEBUG` und `docker logs -f puls-miscale`.

**Die Reichweite ist der Knackpunkt:** BLE schafft je nach Wänden 5–10 m. Steht dein
Server im Keller und die Waage im Bad, funktioniert das nicht — dann bleiben der
CSV-Import (*Mehr → Körperdaten*) oder eine openScale-Bridge nach Garmin Connect.

Die Körperfett-, Muskel- und Wasserwerte sind Schätzungen aus der Impedanz — gut für
den Trend, nicht als absolute Wahrheit. Das Gewicht selbst ist exakt.

## Workouts auf der Fenix 7

„An Garmin" lädt das Workout hoch und plant es aufs Datum. Sobald die Uhr synct, liegt es
unter *Training → Workouts* bzw. im Kalender. Kraftübungen kommen mit dem richtigen
Garmin-Übungsnamen (also mit Animation), Gewicht und deiner Geräte-Notiz („Stufe 7 bei
Füße"). Läufe bekommen deine kalibrierten Tempo-Vorgaben. Klappt der API-Weg mal nicht,
lädst du die FIT-Datei herunter und importierst sie in Garmin Connect.

## Sicherheit

PULS hat bewusst keinen Login (Single-User). Betreib es im eigenen Netz oder hinter
VPN/Tailscale bzw. Cloudflare Tunnel mit Access — im Container liegen deine Garmin-Tokens.
Der Waagen-Webhook ist per Token geschützt.

## Hinweise

- Die Garmin-Anbindung nutzt die **inoffizielle** Connect-API. Garmin kann daran etwas
  ändern — dann hilft meist `docker compose build --no-cache`. Der FIT-Weg funktioniert
  unabhängig davon.
- Der Coach ist kein Arzt. Bei Schmerzen oder gesundheitlichen Fragen: echte Fachleute.
- Täglich laufen plus 3× Gym ist ein ordentliches Pensum. Das Dashboard zeigt deine
  Belastung (ACWR); wenn der Wert über 1,5 klettert, meldet sich der Coach.

## Technik

FastAPI + SQLite (Volume `puls-data`), Ollama als eigener Container, Mi-Scale-Dienst mit
`bleak`, Frontend als abhängigkeitsfreie Vanilla-JS-PWA. Scheduler: Garmin-Sync (alle
`SYNC_INTERVAL_HOURS`), Tagesnachricht (7:30), Forschungs-Häppchen (Mo 6:00).

| Env-Variable | Default | Bedeutung |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:8b` | Startmodell (in der App änderbar) |
| `OLLAMA_TIMEOUT` | `600` | max. Antwortzeit in s (CPU!) |
| `SYNC_INTERVAL_HOURS` | `3` | Garmin-Sync-Intervall |
| `SYNC_LOOKBACK_DAYS` | `14` | wie weit zurück gesynct wird |
| `PULS_PORT` | `1337` | Port, unter dem PULS im Browser läuft |
| `PULS_TOKEN` (miscale) | — | Token aus *Mehr → Waage* |
| `SCALE_MAC` (miscale) | leer | nur auf diese Waage hören |
| `MIN_WEIGHT_KG` (miscale) | `30` | leichtere Messungen ignorieren |

Parser-Tests der Waage: `cd miscale && python3 test_parser.py`
