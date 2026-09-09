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


## Der Coach-Score

Ganz oben auf dem Dashboard steht, wie zufrieden der Coach gerade ist — eine
Zahl von 0 bis 100, und daneben die fünf Säulen, aus denen sie entsteht. Ein
einzelner Wert ohne Begründung wäre leicht misszuverstehen; wer 82 sieht, soll
danebenlesen können, woraus die 82 kommt.

| Säule | Gewicht | Woraus sie entsteht |
|---|---|---|
| Beständigkeit | 30 % | Wie oft du deine eigene Wochenstruktur tatsächlich einhältst |
| Fortschritt | 25 % | Werden Gewichte schwerer und Läufe schneller bei gleichem Puls |
| Erholung | 20 % | Schlaf, HRV und Ruhepuls gegenüber *deiner* Basislinie |
| Belastung | 15 % | Belastungsverhältnis (ACWR) — Aufbau oder Überlastung |
| Alltag | 10 % | Supplements, Wiegen im Referenzfenster, Befinden eintragen |

Säulen ohne ausreichende Datengrundlage werden **nicht geraten**, sondern als
solche ausgewiesen; ihr Gewicht verteilt sich auf die übrigen, damit eine
fehlende Quelle den Wert nicht künstlich drückt.

Darunter steht, **wo am meisten Potenzial liegt** — sortiert danach, was
rechnerisch die meisten Punkte liegen lässt, mit einer konkreten Ansage statt
einer Mängelliste.

Gerechnet wird der Wert im Code. Das Modell darf ihn kommentieren, aber nicht
bestimmen — sonst wäre er von Tag zu Tag beliebig.

## Dein Zustand heute — und was daraus folgt

Ganz oben auf dem Dashboard stehen die sechs Werte, nach denen sich entscheidet,
was heute sinnvoll ist: Ruhepuls, HRV, Schlaf, Stressmittel, Trainingsbereitschaft
und Body Battery beim Aufwachen. Jeder mit seiner Veränderung gegenüber deiner
Basislinie und einem knappen Verlauf.

Darunter schreibt der Coach drei bis vier Sätze dazu, was die Zahlen bedeuten und
was für heute folgt — immer im Bezug zur Basislinie, denn ein Ruhepuls von 46
sagt nichts, solange man deinen Normalwert nicht kennt. Die Einschätzung wird
für die Sitzung behalten, weil sie auf der CPU spürbar dauert.

## Was dir guttut — und was nicht

Die Frage ist nicht, wie hoch deine HRV ist, sondern ob es dir an Tagen mit
hoher HRV besser geht. Auf dem Dashboard steht dafür eine Karte, die genau das
vergleicht: Die Tage werden am Median eines Einflusses in zwei Hälften geteilt,
und Stimmung, Energie und Trainingsbereitschaft in beiden Hälften
gegenübergestellt.

*„An Tagen mit mehr als 7,2 h Schlafdauer: Stimmung 4,1 von 5 — sonst 2,8 von 5."*

Ein Balkenpaar zeigt den Unterschied. Das ist ehrlicher als eine
Korrelationszahl, die niemand einordnen kann — man sieht sofort, ob der
Unterschied groß oder klein ist.

Gemeldet wird nur, was drei Bedingungen erfüllt: mindestens fünf Tage in jeder
Hälfte, über 12 % Unterschied, und ein Zusammenhang, der auch als Korrelation
sichtbar ist. Bei genug Daten wird sonst irgendwann jeder Zufall
„signifikant". Ein Test füttert die Auswertung mit reinem Rauschen und prüft,
dass sie schweigt.

Untersucht werden Schlafdauer, Tiefschlaf, Schlafscore, HRV, Ruhepuls, Stress
und Trainingslast des Vortags. Der Stress von *gestern* erklärt den heutigen
Zustand — der von heute ist teils dessen Folge.

Zusammenhang ist keine Ursache. Die Texte sagen deshalb, was miteinander
einherging, nicht was wovon kommt.

## Nährwerte und was du erreichen solltest

Unter *Essen* trägst du Mahlzeiten ein — von Hand oder mit einem Tipp aus der
Rezeptliste, dann stehen die Nährwerte schon da. Portionen skalieren mit.

Die Zielwerte rechnet PULS aus deinen Daten statt aus einer Tabelle:

- **Grundumsatz** nach Mifflin-St Jeor aus Alter, Größe und Gewicht — die
  Formel, die in Vergleichsstudien am besten abschneidet
- **mal 1,3** für den Alltag ohne Sport
- **plus dein tatsächlicher Trainingsverbrauch** aus den verbrannten Kalorien
  der letzten 14 Tage. Wer täglich läuft und dreimal ins Gym geht, hat einen
  anderen Bedarf als der Durchschnitt gleicher Größe und gleichen Gewichts
- **plus 350 kcal**, wenn „Gewicht zunehmen" unter deinen Zielen steht

Eiweiß mit 1,8 bis 2,2 g je Kilogramm je nach Ziel, Fett mit 0,9 g je
Kilogramm, der Rest Kohlenhydrate. Jeder Wert zeigt mit einem Balken, wie weit
der Tag ist und was noch fehlt. Der komplette Rechenweg steht ausklappbar
darunter — eigene Zielwerte in den Einstellungen haben Vorrang.

## Was jetzt hilft — und was bei dir wirklich hilft

Meldest du gedrückte Stimmung, wenig Energie, hohen Stress oder schlechten
Schlaf, erscheint eine Karte mit drei konkreten Maßnahmen für die nächsten
Stunden — aus Bewegung, Ernährung und Gewohnheiten. Jede ist sofort umsetzbar
und nennt ihren Grund; keine Motivationssprüche.

Der eigentliche Punkt ist die Rückmeldung darunter: **hat geholfen** oder
**bringt mir nichts**. PULS merkt sich das und zieht beim nächsten Mal vor, was
bei dir gewirkt hat. Was zweimal nichts gebracht hat, kommt seltener. Aus einer
allgemeinen Liste wird so mit der Zeit deine Liste — und was sich bewährt hat,
steht auch im Kontext des Coaches, wenn du ihn etwas fragst.

## Rückmeldung nach jeder Einheit

Die Uhr misst Puls und Tempo, aber nicht, ob sich eine Einheit gut angefühlt
hat. Genau diese Größe fehlt: Zwei Läufe mit identischen Daten können sich völlig
verschieden anfühlen, und der Unterschied liegt in Schlaf, Stress und Ernährung
davor.

Deshalb fragt PULS nach jeder Einheit kurz nach — zwei Regler und ein Feld. Ab
sechs Rückmeldungen vergleicht es die Tage vor guten mit denen vor schlechten
Einheiten und sagt, was sich unterscheidet: *„Vor guten Einheiten hattest du im
Schnitt 1,4 h mehr Schlaf als vor schlechten."* Gemeldet wird nur, was deutlich
auseinanderliegt.

## Mit dem Coach sprechen — und was er behält

Der Chat steht direkt auf der Startseite und kennt deine Daten. Damit du nicht
zum dritten Mal erklärst, dass das linke Knie empfindlich ist, hält PULS eine
kleine Zahl von **Merkposten** — Sätze, die dauerhaft gelten.

Zwei Wege hinein: Du trägst sie selbst ein, oder das Modell erkennt nach einem
Gespräch etwas, das über den Tag hinaus gilt (Vorlieben, Unverträglichkeiten,
Verletzungsgeschichte, Arbeitszeiten). Beides landet **sichtbar** in der Liste
unter dem Chat und lässt sich löschen — nichts wird heimlich behalten. Selbst
eingetragene Merkposten sind angeheftet und werden nie verdrängt.

## Was der Coach von sich aus vorschlägt

Deine Wochenstruktur ist der Rahmen und bleibt es. Aber ein Rahmen allein macht
noch kein Training — irgendwann fehlt ein langer Lauf, es wurde wochenlang nur
locker gelaufen, oder die Belastung steigt schneller, als die Erholung
mitkommt. Dafür prüft PULS nach jedem Sync sieben Regeln und legt bei Bedarf
einen Vorschlag auf das Dashboard:

| Regel | Wann sie greift |
|---|---|
| Langer Lauf | 14 Tage ohne Lauf über 50 Minuten — schlägt einen Sonntag vor |
| Tempoeinheit | Alle Läufe nur locker, kein harter Anteil seit 12 Tagen |
| Zu viel Intensität | Unter 68 % der Laufzeit in Zone 1–2 |
| Ruhigere Woche | Belastungsverhältnis über 1,45 |
| Erholungstag | HRV unter, Ruhepuls über der Basislinie — beides zugleich |
| Vernachlässigte Muskelgruppe | Über drei Wochen ohne Satz dafür |
| Klimmzüge | Ziel noch offen, aber kaum Sätze in drei Wochen |

Jeder Vorschlag nennt seinen Anlass und lässt sich mit einem Tipp übernehmen
oder verwerfen — **nichts geht ungefragt an die Uhr**. Bei „Übernehmen" wird
aus dem Vorschlag ein echtes Workout mit Datum, oder ein Schwerpunkt, den die
nächste Gym-Einheit für zwei Wochen berücksichtigt. Verworfenes kommt zehn Tage
lang nicht wieder.

Der Unterschied zu Beschwerden ist Absicht: Auf gemeldete Schmerzen reagiert
PULS sofort und ohne Rückfrage, weil das keine Geschmacksfrage ist. Ein
zusätzlicher Sonntagslauf dagegen ist deine Entscheidung.

## Gemütszustand und Beschwerden

Ein eigener Tab, mehrmals am Tag nutzbar: Stimmung, Energie und Stress auf
einer Fünferskala, antippbare Beschwerden nach Körperregion und Art
(Schmerz, Muskelkater, Verspannung …) und ein Freitextfeld. Schreibst du
„Rücken zwickt seit gestern", liest das lokale Modell das mit und **schlägt**
den passenden Eintrag vor — übernommen wird er erst, wenn du drauftippst.

**Das ändert den Plan, nicht nur die Statistik.** Eine gemeldete
Rückenbeschwerde nimmt die betroffenen Muskelgruppen aus der nächsten
Gym-Einheit und zieht die passenden Yoga-Stellungen im Abendprogramm nach
vorn. Bliebe dadurch zu wenig übrig, wird die Einschränkung wieder aufgehoben
— eine Einheit aus zwei Übungen hilft niemandem.

Beschwerden klingen unterschiedlich schnell ab: Muskelkater zählt drei Tage,
Schmerz sieben, eine Verletzung drei Wochen. Bei Muskelkater kommt ein
Ernährungshinweis dazu, bei Schmerz wird ausgesetzt statt dosiert.

Die Zuordnung von Beschwerde zu Konsequenz steht als Tabelle im Code, nicht
als Modellanfrage: „Rückenschmerzen" muss jedes Mal dasselbe auslösen.

## Supplements

Unter *Mehr → Supplements*. Jedes Mittel ist entweder zu einer festen Uhrzeit
fällig oder an eine Einheit gekoppelt — was am Gym hängt, wird an einem
Ruhetag gar nicht erst fällig, und „wartet noch auf die Einheit" ist etwas
anderes als „vergessen". Nur das Zweite wird hervorgehoben.

Voreingestellt sind Kreatin (5 g morgens), Zink (abends) und ein Eiweiß-Shake
nach dem Gym; alles änderbar. Offene Einnahmen stehen auf dem Dashboard zum
Abhaken und tauchen in der Tagesnachricht des Coaches auf.

## Rezepte

Unter *Essen*. Zwanzig Gerichte mit echten Nährwerten je Portion, gewichtet
auf vegetarisch, schnell und vorkochbar. Die Auswahl trifft der Code aus dem,
was du heute tatsächlich trainiert hast: Krafttraining stellt Eiweiß nach
vorn, ein langer Lauf die Kohlenhydrate, gemeldeter Muskelkater holt die
regenerativen Gerichte dazu, und wenn dir bis zum Eiweißziel noch viel fehlt,
schlägt das alles andere.

Das Modell schreibt nur die zwei Sätze Begründung — es liefert keine einzige
Zahl. Ein 8B-Modell auf CPU würde plausibel klingende Nährwerte erfinden, und
an erfundenen Werten lässt sich keine Bilanz führen. Ein Test rechnet für
jedes Rezept die Kalorien aus den Makros nach, damit ein Tippfehler in der
Tabelle auffällt.

## Erholung

Im Gemüt-Tab: HRV, Ruhepuls, Schlaf mit seinen Phasen, Schlafscore, Body
Battery, Stress und Atemfrequenz. Jeder Wert steht **im Verhältnis zu deiner
eigenen Basislinie** — 58 ms HRV sagen nichts, solange man nicht weiß, was
für dich normal ist.

Zusammenhänge werden nur gemeldet, wenn sie belastbar sind: mindestens
14 Tage Daten und ein Zusammenhang von mindestens 0,35. Sonst würde die
Auswertung Zufall als Einsicht verkaufen.

## Aktivitätsprotokoll, Karten und Kurven

Unter *Übungen* steht das vollständige Protokoll, filterbar nach Sportart und
Zeitraum, mit Summen je Sportart.

Ein **Lauf** öffnet sich mit der GPS-Spur, eingefärbt nach Puls, wahlweise mit
OpenStreetMap-Hintergrund (in den Einstellungen zuschaltbar, standardmäßig
aus — ohne das geht keine Anfrage nach außen). Darunter Puls, Tempo, Höhe und
Schrittfrequenz als Kurven mit einem gemeinsamen Fadenkreuz: Fährst du über
die Kurve, wandert ein Punkt über die Karte. Dazu die Kilometerzeiten.

Eine **Gym-Einheit** öffnet Sätze, Volumen, Muskelgruppen und je Übung den
Vergleich zur letzten Einheit — schwerer, mehr Wiederholungen, unverändert
oder runter. Die Hinweise kommen aus den Zahlen: eine Übung, die stillsteht;
eine, die durchgehend leicht lief; Volumen deutlich über oder unter deinem
Vier-Wochen-Schnitt.

Die Detaildaten werden beim Sync ausgedünnt gespeichert — Kurven auf rund 400
Messpunkte gemittelt, die GPS-Spur mit Douglas-Peucker vereinfacht. An einem
45-Minuten-Lauf gemessen: 539 kB roh, 23 kB gespeichert, größte Abweichung der
Spur 1,2 m. So passt jeder Lauf dauerhaft ins Volume.

## Körperdaten und Referenzfenster

Zwischen der Messung früh nüchtern und der abends nach dem Essen liegen leicht
anderthalb Kilo, ohne dass sich am Körper etwas geändert hätte. Deshalb
arbeitet PULS mit einem **Referenzfenster** (Standard 6–9 Uhr, einstellbar):
Nur Messungen darin bilden die Trendlinie. Alle anderen werden gespeichert,
markiert und über ein Tagesgang-Modell umgerechnet.

Das Modell startet mit Erfahrungswerten und **kalibriert sich auf dich**,
sobald fünf Tage mit Morgen- *und* Abendmessung vorliegen. Messungen ohne
bekannte Uhrzeit (Altbestand, CSV-Import) werden als solche geführt und nicht
korrigiert — eine Uhrzeit zu raten wäre schlimmer als die Lücke.

Die Waage funkt nur Gewicht und Impedanz. Körperfett, Muskelmasse, Wasser,
Knochenmasse und Viszeralfett sind daraus **geschätzt** und in der Oberfläche
mit einem ≈ markiert. Gut für den Trend, nicht als medizinische Aussage.
Jede Messung ist einzeln löschbar.

## Wenn keine Daten ankommen

Unter *Mehr → Garmin → „Es kommen keine Daten an?" → Prüfen*. Das geht der
Reihe nach durch: Ist Garmin verknüpft, steht die Verbindung, liefert Garmin
überhaupt Aktivitäten und Tageswerte, und was davon ist in der Datenbank
gelandet — dazu die letzten Protokolleinträge. Damit lässt sich unterscheiden,
ob die Verbindung, die Abfrage oder das Speichern klemmt.

Der Verlaufs-Import läuft in vier Schritten mit eigenem Fortschritt und lässt
sich abbrechen; das bereits Geholte bleibt. Bleibt er hängen, gilt er nach
fünf Minuten ohne Fortschritt als tot und ist über „Import zurücksetzen"
wieder startbar.

## Tests

```bash
./tests/run_all.sh
```

Zwölf Suiten, alle ohne Netz und gegen Wegwerf-Datenbanken — deine Daten werden
nicht angefasst. Eine davon prüft Eigenschaften, die für die ganze API gelten sollen: dass alle
39 GET-Endpunkte fehlerfrei antworten, dass keiner davon Daten verändert, und
dass zweimal dieselbe Abfrage dasselbe ergibt. Genau dort ist ein Fehler
aufgefallen, den keine einzelne Prüfung gefunden hätte.

Abgedeckt sind ansonsten der Waagen-Parser, das Referenzfenster mit
seiner Kalibrierung, das Ausdünnen der Laufdaten, die Gym-Auswertung, die
Ableitung von Beschwerden bis in den fertigen Trainingsplan, der Garmin-Sync
samt Verlaufs-Import gegen einen nachgebauten Client, die komplette API gegen
die echte Anwendung, und die Frontend-Struktur.

## Installieren und aktualisieren — ein Befehl

Einmalig einrichten:

```bash
mkdir -p /mnt/user/appdata/puls-coach && cd /mnt/user/appdata/puls-coach && \
  wget -qO update.sh https://raw.githubusercontent.com/WanderIust27/Puls/main/update.sh && \
  chmod +x update.sh && ./update.sh
```

Ab dann genügt jedes Mal:

```bash
cd /mnt/user/appdata/puls-coach && ./update.sh
```

Sollte `raw.githubusercontent.com` in deinem Netz nicht erreichbar sein, geht
es auch über das Archiv:

```bash
mkdir -p /mnt/user/appdata/puls-coach && cd /mnt/user/appdata/puls-coach && \
  wget -qO /tmp/p.zip https://codeload.github.com/WanderIust27/Puls/zip/refs/heads/main && \
  unzip -qjo /tmp/p.zip "*/update.sh" -d . && chmod +x update.sh && ./update.sh
```

Das Skript lädt den aktuellen Stand, sichert vorher die Datenbank als
`puls-backup-<Datum>.db` in den Ordner, tauscht nur die Programmdateien aus und
startet über `deploy.sh` neu. Deine `.env` bleibt stehen, die Volumes
`puls-data` und `ollama-data` werden nicht angefasst.

| Aufruf | Wirkung |
|---|---|
| `./update.sh` | holen, austauschen, deployen |
| `./update.sh --no-deploy` | nur die Dateien austauschen |
| `PULS_BRANCH=xyz ./update.sh` | einen anderen Branch nehmen |

Wenn etwas klemmt, zeigt `sh -x update.sh` jeden Schritt einzeln — daran ist
meist sofort zu sehen, woran es hängt.

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

### Grafikkarte für das KI-Modell

Standardmäßig rechnet Ollama auf der CPU, damit die Karte für andere Dienste
frei bleibt. Einschalten:

```bash
./deploy.sh gpu on      # trägt OLLAMA_GPU=all in die .env ein
./deploy.sh             # übernehmen
```

Hast du mehrere Karten und willst nur eine abgeben, nimm ihre UUID aus
`nvidia-smi -L`:

```bash
./deploy.sh gpu on GPU-57266007-2214-4d3e-9579-09f114a625b8
```

Wieder abschalten: `./deploy.sh gpu off`, dann `./deploy.sh`.

Voraussetzung ist, dass Docker eine Karte durchreichen kann — auf Unraid das
Plugin **Nvidia Driver** aus den Community Apps, danach den Server einmal neu
starten.

Ob es klappt, sagt dir:

```bash
./deploy.sh gpu
```

Das prüft in vier Schritten Treiber, Docker-Runtime, Durchreichbarkeit und ob
der laufende Container die Karte tatsächlich sieht. Geprüft wird dabei auf die
Gerätedatei `/dev/nvidia0`, nicht auf `nvidia-smi`: Das Ollama-Image bringt
diese Binary nicht mit, ein Test darauf würde also auch dann scheitern, wenn
alles läuft. Beim Deployen wird dasselbe
noch einmal geprüft: Ein Container, der zwar startet, aber keine Karte sieht,
wäre sonst nicht von einem mit Karte zu unterscheiden — er würde still auf der
CPU rechnen.

Der Unterschied ist erheblich: Auf der CPU dauert eine Coach-Antwort mit
Qwen3-8B je nach Kernen ein bis mehrere Minuten, auf einer Karte Sekunden.
Achte auf den VRAM: Qwen3-8B braucht rund 5–6 GB. Passt das Modell nicht ganz
hinein, teilt Ollama auf — und das ist dann langsamer als reine CPU. Bei
weniger Speicher lieber `qwen3:4b` unter *Mehr → KI-Modell*.

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

Diagramme und Karte sind selbst gezeichnetes Inline-SVG — auch die Karte, denn
eine unbewegliche Karte braucht keine Kartenbibliothek: Es genügt, die
Kachelnummern für den Ausschnitt auszurechnen und die Bilder an die richtige
Stelle zu legen. Das sind ein paar Zeilen statt 150 kB Fremdcode.

Der durchgehende Grundsatz: **Der Code rechnet, das Modell formuliert.**
Trainingsgewichte, Tempozonen, 1RM, VO₂max, Progression, Nährwerte und der
Score sind deterministisch. Das Modell wählt aus und erklärt — es erfindet
keine Zahlen.

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
