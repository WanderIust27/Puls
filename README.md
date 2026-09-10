# PULS — dein lokaler Trainingscoach

Selbstgehosteter Trainingscoach mit lokaler KI (Ollama, rein auf CPU), Garmin-Anbindung
in beide Richtungen, Übungsbibliothek mit automatischer Progression und einem dunklen,
motivierenden Dashboard. Läuft komplett auf deinem Server — keine Cloud-KI, keine Abos.

## Die Reiter

| Reiter | Was dort steht |
|---|---|
| **Start** | Score, was der Coach heute sagt, offene Punkte, nächste Einheiten, zuletzt Trainiertes samt Bewertung, Schlafenszeit, Chat |
| **Gemüt** | Stimmung eintragen, was der Coach daraus macht, „Was jetzt hilft", Verlauf |
| **Plan** | Ziel, Wochenstruktur, die kommende Woche, geplante Einheiten, Kalibrierung |
| **Kraft** | Muskelgruppen, Trainingslast, Übungsbibliothek, manuelles Eintragen |
| **Laufen** | Laufform und Prognosen, Lauftrends, Aktivitätsprotokoll |
| **Essen** | Tagesbilanz, Freitext-Eingabe, Rezeptvorschläge, Verlauf |
| **Gewicht** | Referenzfenster, Körperzusammensetzung, Verlauf |
| **Vital** | Zustand heute, Schlaf, Herz, Erholung |
| **Statistik** | Alles gegen alles, abgeleitete Empfehlungen |
| **Mehr** | Garmin, Waage, Supplements, Ziele, Darstellung, Modell, Version |

Zehn Reiter passen auf einem Telefon nicht nebeneinander — die Leiste scrollt
seitlich, und der aktive Reiter wird beim Wechsel in den Blick geholt.

## Deine Wochenstruktur

PULS plant genau so, wie du trainierst:

| Wann | Was |
|---|---|
| Jeden Morgen | 20–30 min Laufen — meist locker, ein Tempo- und ein langer Lauf pro Woche |
| Mo / Mi / Fr abends | Gym 60–90 min: Kettlebell-Auftakt → Klimmzug-Arbeit → Maschinen → Dehnen |
| Jeden Abend | Kurze Yoga-/Dehneinheit vor dem Schlafen |

Alles davon stellst du im **Coach-Tab** um: Gym-Tage und Lauftage getrennt
anklicken, Dauer setzen, Ziel hineinschreiben — den Rest legt der Coach fest
(siehe *Der Coach-Tab*). Ein Klick auf **Woche planen** erzeugt die komplette
Woche; **Alles an Garmin** schiebt sie auf die Fenix.

## Die zwei Hauptziele

- **10 km unter 60 Minuten** — der Benchmark-Lauf kalibriert deine Trainingstempi, das
  Dashboard zeigt die aktuelle Prognose und wie weit du noch weg bist.
- **Mehr Klimmzüge** — eigener Block in jeder Gym-Einheit. Je nach Maximum arbeitet PULS
  mit negativen, bandunterstützten oder freien Klimmzügen.

## Wann du ins Bett solltest

Abends steht auf der Startseite eine Uhrzeit. Sie ist rückwärts gerechnet:

    Zubettgehzeit = Aufstehziel − Schlafbedarf − Einschlafdauer

Das **Aufstehziel** stellst du unter *Mehr → Trainingsziele* ein. Der
**Schlafbedarf** ist keine feste Zahl: acht Stunden als Grundlage, plus je eine
halbe Stunde bei schwacher Trainingsbereitschaft, bei einer HRV deutlich unter
deinem Schnitt und nach einer langen Einheit, dazu bis zu einer halben Stunde
für den Rückstand der letzten Nächte. Jeder Zuschlag wird benannt — wer ihn für
falsch hält, sieht sofort, woran es liegt. Die **Einschlafdauer** kommt aus
deinen eigenen Nächten (Zeit im Bett minus tatsächlich geschlafene Zeit), sobald
fünf davon vorliegen; vorher gilt ein Vorgabewert von 15 Minuten.

Darunter steht, wie regelmäßig es tatsächlich zugeht: um wie viel deine
Zubettgeh- und Aufstehzeiten im Schnitt schwanken, und an wie vielen Nächten du
deutlich später aufgestanden bist als geplant. Regelmäßigkeit bringt hier mehr
als eine einzelne lange Nacht — deshalb steht sie daneben und nicht in einer
Fußnote.

Die Karte erscheint ab dem späten Nachmittag. Beim Frühstück hilft sie nicht.

## Wie lange eine Einheit wirklich dauert

Eine Gym-Einheit, die „90 min" heißt und nach 80 vorbei ist, ist eine Ansage,
auf die man sich nicht verlassen kann. Genau das war lange der Fall: Die Zahl
kam aus einer Nachschlagetabelle mit drei Einträgen (60/75/90), die festlegte,
wie viele Übungen in jeden Block kommen — wie lange das dann dauert, hat nie
jemand nachgerechnet. Jeder Wunsch dazwischen rutschte auf einen der drei
Werte, 68 Minuten ergaben dieselbe Einheit wie 75.

Jetzt wird gerechnet. Jede Wiederholung zählt mit dreieinhalb Sekunden (zwei
hoch, zwei runter, plus Ansetzen), jede Pause und jede Zeitübung mit ihrer
Dauer, dazu 45 Sekunden Umsetzen je Übung — Gewicht einstellen, Gerät suchen.
Danach werden Übungen zugefügt oder weggenommen, bis die Einheit die Vorgabe
auf ±7 % trifft: erst im Hauptteil, dann Kettlebell und Klimmzüge, das Dehnen
zuletzt. Genauer geht es nicht sinnvoll — die kleinste Einheit ist eine Übung,
und die dauert rund fünf Minuten.

Im Namen steht danach die **gerechnete** Dauer, nicht die gewünschte. Wer 75
Minuten einstellt, bekommt womöglich „Gym Ganzkörper 80 min" — das ist keine
Ungenauigkeit, sondern die ehrliche Zahl.

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

## Einheit auf Zuruf

Ein Eingabefeld unter *Plan*. Schreib hinein, was du willst:

| Was du schreibst | Was daraus wird |
|---|---|
| „90 Minuten Ganzkörper" | 89-min-Gym-Einheit über alle Gruppen |
| „30 Minuten zuhause, Fokus Bauch" | 30 min auf der Matte, nur Rumpf |
| „45 min Push im Studio" | Brust, Schultern, Arme |
| „60 Minuten zuhause für den Handstand" | Handgelenke → Handstand an der Wand → Pike-Liegestütz → Hohlkörper → Krähe |
| „eine Stunde zuhause für den ersten Klimmzug" | Negative Klimmzüge, Rudern, Rumpfarbeit |

Über dem Vorschlag steht, **wie der Satz gelesen wurde** („60 Minuten zuhause,
auf Handstand hin — Schultern, Rumpf, Arme"). Wer eine Einheit bekommt, die
nicht zum Wunsch passt, soll sehen, woran es lag.

Die Arbeitsteilung ist die übliche: Das Modell liest Dauer, Ort, Schwerpunkt und
ein etwaiges Ziel heraus — mehr nicht. Welche Übungen daraus werden, entscheidet
der Code aus der Bibliothek. Ein Modell, das sich Übungen ausdenkt, erfindet
auch Gewichte, und die stünden dann im Plan. Ohne laufendes Modell zerlegt PULS
den Satz selbst; alle Beispiele oben funktionieren auch dann.

Zielorientierte Übungen (Handstand an der Wand, Krähe, Pike-Liegestütz) tauchen
**nur** auf, wenn ein Ziel sie verlangt. In einer beliebigen Bauch-Einheit haben
sie nichts verloren. Umgekehrt darf eine verlangte Übung aus jedem Block kommen:
Wer auf den ersten Klimmzug hinarbeitet, braucht negative Klimmzüge — egal, in
welcher Schublade sie liegen.

## Ein Schwerpunkt trägt die Einheit

„90 Minuten Gym, Sixpack" ergab lange **eine** Bauchübung von sechs. Zwei
Gründe: Der Hauptteil ging stur reihum durch alle Muskelgruppen, und die
Matten-Übungen — Sit-ups, Planken, Seitstütz — lagen im Block „zuhause" und
waren im Studio damit gesperrt. Als hinge ein Sit-up an einer Maschine.

Beides ist geändert. Matten-Übungen haben einen eigenen Block und kommen
**sowohl zuhause als auch im Studio** in Frage. Und bei einem ausdrücklichen
Wunsch trägt der Schwerpunkt den Hauptteil, statt nur vorne zu stehen: Auftakt
und Klimmzugarbeit schrumpfen zugunsten der gewünschten Gruppen, ein
Kettlebell-Satz bleibt als Aufwärmen stehen. Dazu sechs neue Studio-Übungen für
den Rumpf: Sit-ups, Negativ-Sit-ups an der Schrägbank, Rumpfrotation,
Rückenstrecker, hängendes Beinheben, Crunch am Kabelzug.

Aus „90 Minuten Gym Sixpack" wird damit:

    Aufwärmen (Kettlebell)
    Klappmesser · Sit-ups · Hängendes Beinheben
    Unterarmstütz · Seitstütz · Käfer
    Beinpresse
    Negativ-Sit-ups · Rumpfrotation · Crunch am Kabelzug
    Dehnen

Die Reihenfolge ist kein Zufall: **Matte vor Maschine.** Nach dem Aufwärmen
liegt man ohnehin schon, und die Geräte sind später frei. Ein breiter Wunsch
(„Ganzkörper") bleibt dagegen ausgewogen — dort ist die Gleichverteilung ja
gerade der Punkt.

Neue Übungen erreichen auch eine **bestehende** Bibliothek: Gesät wird nur beim
ersten Start, deshalb trägt ein Abgleich beim Hochfahren nach, was dazugekommen
ist. Angefasst wird dabei nichts Bestehendes — eigene Gewichte, Zielwerte und
selbst angelegte Übungen bleiben unberührt.

## Zuhause trainieren

Nicht jede Einheit braucht ein Studio. Unter *Plan → Zuhause trainieren* wählst
du Dauer und Muskelgruppen, und PULS baut eine Einheit aus Übungen, die nichts
als eine Matte und höchstens eine kleine Hantel brauchen: Unterarmstütz,
Seitstütz, Käfer, Vierfüßlerstand, Beckenheben, Rückenstrecken, Schwimmer,
einarmiges Rudern, Kurzhantel-Kreuzheben, Seitheben, Überzüge, russischer
Twist, Liegestütz, Ausfallschritte.

Die Gruppen wechseln sich ab, statt sechsmal Bauch zu bringen. Die Dauer wird
eingehalten — Übungen kommen dazu oder fallen weg, bis sie passt. Gemeldete
Beschwerden gelten auch hier: Bei Rückenschmerzen bleibt der Rücken draußen,
und das steht dann auch da. Ohne Hantel geht es ebenfalls, dann bleiben die
Körpergewichtsübungen.

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

Der Zeitraum ist bewusst kurz: Beständigkeit zählt die laufende **Woche**,
Alltagsgewohnheiten ebenfalls, nur der Fortschritt braucht vier Wochen, weil
sich Kraft und Tempo in sieben Tagen nicht messbar ändern. Ein Monatswert
verwischt genau das, worauf du heute noch Einfluss hast — nach einer guten
Woche soll der Wert steigen, nicht in einem Durchschnitt untergehen.

Direkt daneben steht **was heute noch offen ist**: Lauf, Gym, Abend-Yoga,
Schritte, Supplements, Wiegen im Referenzfenster, Befinden. Jeder Punkt mit
seinem Fortschritt, am Abend im besten Fall alles erledigt. Zweimal am Tag —
mittags und abends — meldet sich der Coach von sich aus dazu, wenn noch etwas
offen ist, mit zwei Sätzen dazu, was jetzt noch machbar ist. Beim Schrittziel
nennt er den Stand, damit „noch 2.400 Schritte" auch als Spaziergang lesbar ist.

Gerechnet wird der Wert im Code. Das Modell darf ihn kommentieren, aber nicht
bestimmen — sonst wäre er von Tag zu Tag beliebig.

## Dein Zustand heute — und was daraus folgt

Ganz oben auf dem Dashboard stehen die sechs Werte, nach denen sich entscheidet,
was heute sinnvoll ist: Ruhepuls, HRV, Schlaf, Stressmittel, Trainingsbereitschaft
und Body Battery beim Aufwachen. Jeder mit seiner Veränderung gegenüber deiner
Basislinie und einem knappen Verlauf.

Werte mit einer festen Skala stehen als **„62 von 100"** da, mit einem Balken
darunter, der zusätzlich den Bereich markiert, in dem sie bei dir normal liegen.
Eine nackte 62 sagt nichts, solange man weder die Obergrenze noch deinen
Normalbereich kennt.

Darunter schreibt der Coach drei bis vier Sätze dazu, was die Zahlen bedeuten und
was für heute folgt — immer im Bezug zur Basislinie, denn ein Ruhepuls von 46
sagt nichts, solange man deinen Normalwert nicht kennt. Die Einschätzung wird
für die Sitzung behalten, weil sie auf der CPU spürbar dauert.

## Statistik — alles gegen alles

Die eigene Ansicht **Statistik** vergleicht jede erfasste Größe mit jeder
anderen: Schlaf gegen Schritte, HRV gegen Gewicht, Body Battery gegen gefühlten
Stress. 37 Größen aus sieben Gruppen — Schlaf, Herz, Stress, Bewegung, Körper,
Befinden, Ernährung.

Das ist statistisch heikel, und genau daran scheitern die meisten solchen
Ansichten: Bei 37 Größen gibt es über 600 Paare. Prüft man die einfach alle
gegen die übliche Schwelle von 5 %, findet man rein durch Zufall **rund
dreißig „Zusammenhänge"**, die keine sind. Wer daraus Empfehlungen ableitet,
folgt Rauschen.

Erfasst sind dabei auch die Dinge, die man leicht vergisst, weil sie keine
Messwerte im engeren Sinn sind:

* **Uhrzeiten** — Zubettgehzeit, Aufstehzeit und Schlafmitte, dazu die
  Abweichung von deiner üblichen Zeit als Maß für Regelmäßigkeit. Und die
  Uhrzeit, zu der du trainierst. Gerechnet wird ohne Bruch um Mitternacht:
  23:30 und 00:30 liegen eine Stunde auseinander, nicht dreiundzwanzig — sonst
  wäre jeder Zusammenhang mit der Schlafenszeit rechnerisch zerstört.
* **Gemüt getrennt nach Tageszeit** — Stimmung und Energie morgens sagen etwas
  über die Nacht, abends etwas über den Tag. Ein Tagesmittel verliert genau
  diesen Unterschied. Dazu der Verlauf über den Tag als eigene Größe.

PULS macht deshalb zweierlei:

* Ein Paar wird überhaupt erst betrachtet, wenn es **mindestens zwölf Tage**
  gibt, an denen beide Werte vorliegen.
* Über alle geprüften Paare läuft eine **Korrektur für Mehrfachprüfung**
  (Benjamini-Hochberg, 10 %). Sie zieht die Grenze so, dass unter den als
  belastbar markierten Funden höchstens jeder zehnte zufällig ist.

Oben stehen die belastbaren Funde, darunter nach Stärke der Rest — sichtbar
ausgegraut, damit der Unterschied nicht in einer Fußnote verschwindet. Zu jedem
Fund gehören Richtung, Stärke, der Korrelationskoeffizient und die Anzahl
gemeinsamer Tage. Auf Knopfdruck ordnet der Coach die stärksten Funde ein — mit
der ausdrücklichen Auflage, offenzulassen, was Ursache und was Wirkung ist. Ein
Zusammenhang zwischen Schlaf und HRV sagt nicht, welches von beidem das andere
treibt.

Jede Größe lässt sich einzeln öffnen: ihr Verlauf, und alles, was mit ihr
zusammenhängt.

### Was daraus folgt

Ein Korrelationskoeffizient ist keine Empfehlung. Über den belastbaren Funden
steht deshalb eine Karte, die daraus etwas Handfestes macht — und zwar
gerechnet, nicht formuliert.

Für jeden Fund, bei dem eine Seite etwas ist, woran du **direkt drehen kannst**
(Schlafenszeit, Schritte, Trainingsumfang, Nährwerte), wird das Drittel deiner
besten Tage gegen das Drittel deiner schlechtesten gestellt und der Unterschied
in echten Einheiten ausgerechnet:

> **Zubettgehzeit vor 22:46** — an diesen 39 Tagen lag deine HRV bei 66 ms
> statt 52,8 ms. Ein Unterschied von 13,2 ms (25 %).

Aus „r = 0,52" wird so eine Uhrzeit, auf die man heute Abend achten kann. Die
Gegenrichtung wird ausgeschlossen: „Schlaf besser, dann ist dein Ruhepuls
tiefer" ist keine Empfehlung, sondern eine Umformulierung des Befunds — nur
Größen, an denen du drehen kannst, kommen als Stellschraube in Frage, und nur
Größen, bei denen klar ist was besser wäre, als Ziel.

Sortiert wird nach Wirkung gemessen am eigenen Streubereich der Zielgröße, nicht
nach der nackten Zahl — sonst gewänne immer die Größe mit den größten Werten.
Je Stellschraube steht nur die stärkste Empfehlung, sonst stünde dreimal
dasselbe da. Und darunter der Hinweis, der bleiben muss: Die Richtung ist damit
nicht geklärt. Dass du an frühen Abenden erholter bist, kann am frühen
Zubettgehen liegen — oder daran, dass man an erholten Tagen früher müde wird.
Als Ansatzpunkt taugt es trotzdem: zwei Wochen ausprobieren, dann hier
nachsehen.

## Der Coach-Tab — Ziel, Woche, Trends

Alles, was das Training bestimmt, steht auf einer Seite: was du erreichen
willst, an welchen Tagen du kannst, wie sich deine Werte entwickeln, und was
daraus für die kommende Woche folgt.

### Dein Ziel

Ein Freitextfeld. Schreib hinein, worauf du hinarbeitest — „10 km unter 55
Minuten, dazu stärkere Beine". PULS liest daraus die Schwerpunkte und zeigt
direkt darunter, was es verstanden hat. Erkannt wird über eine feste
Stichwortliste im Code, nicht vom Modell: Bei „Halbmarathon" soll immer
dasselbe passieren, nicht mal so und mal so. Wird nichts erkannt, steht das da
— dann fehlt eine Strecke, eine Zeit oder eine Übung.

Dazu ein Schwerpunkt (schneller laufen, Muskeln aufbauen, beides halten,
ruhiger werden) und die Dauer je Lauf und je Gym-Einheit.

### Deine Woche

Du sagst nur, **an welchen Tagen du was machst** — Gym-Tage und Lauftage
getrennt. Mo/Mi/Fr ins Gym, Di/Do laufen: zwei Reihen anklickbarer Tage, mehr
nicht. Welche Einheit genau auf welchem Tag landet, entscheidet der Coach jede
Woche neu.

| Was du festlegst | Was der Coach daraus macht |
|---|---|
| Gym an Mo/Mi/Fr | Drei Krafteinheiten, jede mit dem Schwerpunkt, der gerade am ehesten dran ist |
| Laufen an Di/Do | Zwei Läufe — welche Art, entscheidet, was zuletzt gefehlt hat |
| Langer Lauf möglichst am | Liegt auf diesem Tag, wenn es ein Lauftag ist, sonst auf dem letzten |
| Aufteilung der Krafteinheiten | Ganzkörper, Push/Pull, Push/Pull/Beine oder Oberkörper/Beine |
| Abend-Yoga | Jeden Abend zwölf Minuten, oder gar nicht |

**Die Aufteilung** bestimmt, was auf welchem Gym-Tag liegt. Ganzkörper ist für
zwei bis drei Einheiten die Woche das Sinnvollste — jede Gruppe kommt mehrmals
dran. Ab drei lohnt eine Teilung, weil sonst jede Einheit zu lang wird oder zu
wenig je Gruppe übrigbleibt. Bei Mo/Mi/Fr und Push/Pull heißt das Push · Pull ·
Push, bei Push/Pull/Beine entsprechend die Dreiteilung.

Bei einer Teilung gibt der Zyklus den Schwerpunkt vor, nicht die Trends: Eine
Push-Einheit ist eine Push-Einheit, auch wenn die Beine gerade am ehesten dran
wären. Die Trends entscheiden dann *innerhalb* der Gruppe, welche Übung
vorgezogen wird.

Trägst du keine Tage ein, verteilt der Coach selbst — dann zählt nur der
Schwerpunkt. Und wenn die Erholung kippt, fällt ein Tag weg; das steht dann
sichtbar in der Vorschau, statt still zu geschehen.

### Trends: was gefordert werden sollte

Damit „der Coach entscheidet" nicht heißt „irgendetwas passiert", steht daneben
die Grundlage, auf der er entscheidet — gerechnet aus deinen Sätzen und Läufen,
vier Wochen gegen die vier davor.

**Muskelgruppen.** Je Gruppe: Volumen, Anteil am Gesamtvolumen gegen einen
ausgewogenen Zielanteil, Zahl der Einheiten, Tage seit der letzten Belastung
und die Entwicklung der geschätzten Maximalkraft (Epley, über die Übungen
gemittelt, die in beiden Zeiträumen vorkommen — sonst verglichte man Äpfel mit
Birnen). Daraus ein Bedarfswert von 0 bis 100 aus vier Gründen, jeder mit
eigener Obergrenze, damit keiner allein die Rangfolge bestimmt:

* lange nicht trainiert (eine Gruppe, die vier Wochen ausblieb, springt nach oben)
* zu kleiner Anteil am Volumen
* Maximalkraft steht oder fällt
* Volumen eingebrochen

Die oberste Gruppe wird zum Schwerpunkt der nächsten Krafteinheit — die
Übungsauswahl zieht sie vor, statt stur reihum zu gehen. Jede Zeile nennt ihren
Grund, damit man widersprechen kann.

**Der Balken zeigt den Bedarf, nicht die Leistung.** Ein hoher Wert heißt: Diese
Gruppe kommt zu kurz. Was gerade trainiert wurde, *sinkt* hier also — wer heute
Beinpresse gemacht hat, sieht die Beine bei „versorgt · Bedarf 0/100" und nicht
bei 100. Das ist so gewollt, und es steht seit dieser Version auch so über der
Liste; vorher las sich „0 von 100" wie eine schlechte Note.

**Laufen.** Der ehrlichste Fortschrittsmaßstab ist das Tempo bei gleichem
Puls: gleiche Anstrengung, mehr Strecke. Verglichen werden nur Läufe über 2 km
mit einem Durchschnittspuls zwischen 120 und 155 — sonst verglichte man einen
Intervall mit einem Regenerationslauf. Dazu Wochenumfang, längste Einheit und
wie viele Läufe im harten Bereich lagen.

Daraus folgt direkt, was die Woche trägt: Fehlt seit vier Wochen jeder harte
Lauf, kommt einer dazu — auch bei einem Schwerpunkt, der eigentlich keinen
vorsieht. Lagen umgekehrt mehr als 40 % der Läufe im harten Bereich, fällt der
Tempoanteil weg; der Großteil des Laufens gehört ins Lockere. Erkannt wird das
am Puls, nicht am Namen der Einheit: Der Name sagt, was geplant war, der Puls,
was gelaufen wurde.

### Die kommende Woche

Der Plan steht **nach Datum sortiert, das Nächste oben** — was morgen ansteht,
sucht man nicht unten.

**Übernehmen ersetzt die Woche, es legt sie nicht dazu.** Vorher hat jeder
Klick eine weitere komplette Woche obendrauf gelegt — nach dreimal Ausprobieren
standen einundzwanzig Einheiten im Plan. Entfernt wird nur, was noch offen ist
und von einem Planer stammt; Erledigtes, an die Uhr Geschicktes und selbst
Angelegtes bleibt. Ebenso verschwinden Einheiten, deren Datum vorbei ist und
die nie abgehakt wurden: Sie können nicht mehr stattfinden, und stehenzulassen
hieße den Plan mit Unerledigbarem zu füllen.

Die Vorschau zeigt jeden Tag mit Begründung, bevor irgendetwas angelegt wird:
welche Laufart und warum, welcher Kraft-Schwerpunkt und warum, welche Tage die
Erholung gekostet hat. Erst „Übernehmen" schreibt sie in die Planung — und baut
dabei für jede Laufart den passenden Bauplan, nicht überall denselben lockeren
Lauf mit anderem Tempofenster.

Das Modell begründet die Woche hinterher in drei bis vier Sätzen. Es legt sie
nicht fest: Sonst sähe jede Woche anders aus, ohne dass sich etwas geändert
hätte.

## Schlaf

Der Schlaf hat auf dem Dashboard eine eigene, breite Karte: Dauer, Score,
Tief- und REM-Anteil, Wachzeit und Effizienz, jeweils gegen deine Basislinie.
Die Verläufe zeichnen den Wert als Linie über einem grauen Band — dem Bereich,
in dem er bei dir normal liegt. Punkte erscheinen nur dort, wo der Wert das
Band verlässt. Damit ist auf einen Blick erkennbar, welche Nacht aus der Reihe
fiel, ohne dass man Zahlen vergleichen müsste.

Auf Knopfdruck sagt der Coach, was konkret *deinen* Schlaf verbessern würde —
und stützt sich dabei auf die Zusammenhänge, die die Statistik bei dir gefunden
hat, nicht auf allgemeine Schlafregeln.

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

## Essen beschreiben statt Zahlen suchen

„150 g Hähnchen mit Reis und Gemüse, dazu ein Skyr" — eintippen, *Berechnen*,
fertig. Was dabei herauskommt, steht als Aufstellung da, bevor irgendetwas
gebucht wird: jeder Bestandteil einzeln mit Menge und Kalorien, darunter die
Summe.

Die Arbeitsteilung ist dieselbe wie überall hier. Das Modell **zerlegt** den
Satz in Bestandteile und Mengen („zwei Eier" → Ei, 120 g). Die Nährwerte kommen
aus einer Tabelle im Code, nicht aus dem Modell: Ein lokales 8B-Modell auf der
CPU rechnet Kalorien nicht zuverlässig — es schätzt sie, und zwar jedes Mal
anders. Eine Tabelle schätzt auch, aber gleichbleibend und nachschlagbar.

Läuft kein Modell, zerlegt PULS den Text selbst — gröber, aber es funktioniert:
„150 g Hähnchenbrust, 80 g Reis und Gemüse" wird auch ohne Ollama richtig
aufgelöst. Was die Tabelle nicht kennt, wird **benannt und weggelassen**, nicht
geraten: „Nicht gefunden: Mondgestein. Diese Anteile fehlen in der Summe."

Alle rund fünfzig Tabelleneinträge werden von einem Test gegengeprüft — Eiweiß
und Kohlenhydrate 4 kcal/g, Fett 9 —, damit ein Tippfehler in einer Spalte
auffällt statt still in die Tagesbilanz zu wandern.

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

Die Auswahl gilt für **zwei Stunden**. Sie wechselt also im Lauf des Tages,
aber nicht bei jedem Neuladen der Seite — sonst stünde dort ständig etwas
anderes, und die Rückmeldung darunter würde bedeutungslos, weil sie sich auf
einen Vorschlag bezöge, den man nie umgesetzt hat. Im nächsten Fenster kommen
bevorzugt Maßnahmen, die heute noch nicht dran waren.

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

## Schritte: Ziel und Tagesrhythmus

Ein Schrittziel allein sagt am Nachmittag wenig: 6.000 von 10.000 sind um zehn
Uhr viel und um zwanzig Uhr wenig. Auf der Startseite steht deshalb neben dem
Stand, **was zu dieser Stunde bei dir üblich ist** — und was daraus bis
Mitternacht wird, wenn der Tag normal weiterläuft. Reicht es nicht, steht da,
wie viele Minuten Gehen fehlen.

Dafür wird der Tagesverlauf stundenweise von der Uhr geholt. Unter *Vital*
steht der typische Tag als Balken: stärkste Stunde, wann die Hälfte des
Pensums erreicht ist, wie sich morgens, nachmittags und abends verteilen.
Gerechnet wird der **Median** je Stunde, nicht der Mittelwert — ein einzelner
Wandertag soll den Normalfall nicht verschieben.

## Das Layout gehört dir

Jede Karte hat oben links einen Griff (⠿) und daneben drei Zahlen: **1, 2, 3**
— so viele Spalten breit soll sie sein. Was davon ankommt, hängt am Fenster: In
der dreispaltigen Ansicht sind alle drei Breiten verschieden, in der
zweispaltigen sind zwei und drei dasselbe, und auf dem Telefon ist ohnehin jede
Karte volle Breite — dort wird die Wahl deshalb gar nicht erst angeboten.

Mit dem Griff lässt sich die Karte verschieben;
die Reihenfolge bleibt **je Ansicht** gespeichert — und zwar auf dem Server,
nicht im Browser: Am Telefon steht sie danach genauso wie am Rechner. Ohne Maus geht es auch:
Griff anwählen, dann Pfeiltasten. Unter *Mehr → Darstellung* steht ein Knopf,
der die Anordnung der gerade offenen Ansicht zurücksetzt.

Gespeichert werden Reihenfolge und Breiten je Ansicht. Karten, die mit einem Update
dazukommen, hängen hinten an, statt zu verschwinden — eine gespeicherte
Reihenfolge darf ein Update nicht überleben, indem sie neue Karten
unterschlägt.

## Diagramme: Zeitraum und Beschriftung

Über jedem Verlaufsdiagramm steht ein Umschalter. Die Wahl bleibt **je
Diagramm** gespeichert — wer sich den Gewichtsverlauf über ein Vierteljahr
ansieht, steht nach dem Neuladen nicht wieder auf der Woche.

Die Achsenbeschriftung richtet sich nach der Spanne, nicht nach einer festen
Regel: Stunden bei einem Tag (`08:00`), Wochentage bei einer Woche (`Do 3.`),
Datum bei einem Monat (`17.8.`), Monatsnamen bei einem Jahr. Dasselbe gilt für
den Tooltip.

Der **Gemütsverlauf** liegt auf einer echten Zeitachse: Jeder Eintrag steht an
seiner Uhrzeit. Drei Einträge um 7, 13 und 21 Uhr sind kein
Drittel-Drittel-Drittel, und zwei Tage ohne Eintrag sind eine Lücke — die
Linie bricht dort ab, statt nahtlos durchzulaufen und eine Messung
vorzutäuschen, die es nicht gab. Stimmung, Energie und Stress liegen als drei
Kurven übereinander, mit Legende.

Diagramme mit **einem Wert je Tag** (Gewicht, Schlafdauer, Ruhepuls, HRV,
Belastung) bieten bewusst *keine* Tagesansicht an: Ein Tag wäre ein einzelner
Punkt. Einen Umschalter anzubieten, der nichts zeigen kann, wäre ein
Versprechen, das die Daten nicht halten. Sie beginnen bei der Woche.

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

## Warum das angezeigte Gewicht nicht der Waagenwert ist

Drei Zahlen, und sie sind bewusst verschieden:

    82,9 kg  gemessen um 21:40
    81,6 kg  umgerechnet auf dein Referenzfenster
    81,4 kg  Referenzwert (Median über sieben Tage)

Die Kette steht so auf der Seite, weil ein Kopfwert, der zwei Kilo unter der
Waage liegt, ohne Erklärung schlicht unglaubwürdig ist.

Zwei Dinge waren daran lange falsch. Der „7-Tage-Median" lief über die letzten
sieben **Einträge**, nicht über sieben Tage — wer unregelmäßig wiegt, bekam
damit einen Median über Monate, und oben stand ein Gewicht von vor einem
Vierteljahr. Und die Umrechnung auf das Referenzfenster war nach oben nur sehr
weit gedeckelt: Bei verrauschten Messpaaren konnte der persönliche Faktor auf
das Zweieinhalbfache laufen und aus 82,9 kg rechnerisch 79,5 machen.

Jetzt gilt: Der Median läuft über sieben **Kalendertage**, der persönliche
Faktor bleibt zwischen 0,6 und 1,6, und die Umrechnung selbst ist auf 2,5 %
begrenzt. Eine Korrektur, die größer ist als der Unterschied, den man messen
wollte, schadet mehr als sie nutzt.

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

## Nach dem Training: Vorschläge statt stiller Änderungen

Wer 35 kg bewegt, wo 20 geplant waren, hat eine Entscheidung getroffen. PULS
rechnet sie durch und **legt sie vor**, statt sie stillschweigend zu
übernehmen — mit dem Beleg daneben, damit man nicht raten muss, woher die Zahl
kommt:

> **Beinpresse** — 20 kg → **35 kg**
> 15× 35 kg geschafft (Vorgabe 15× 20 kg)
> Du hast 35 kg bewegt, geplant waren 20 kg — das ist die neue Grundlage.
> [Übernehmen] [Lassen]

Vier Fälle werden unterschieden, und der erste ist der, an dem die alte
Automatik scheiterte:

Maßgeblich ist der **schwerste Satz** des Tages, nicht der Durchschnitt. Wer
sich innerhalb einer Einheit hocharbeitet — 25, dann 30, dann 35 kg —, hat mit
dem letzten Satz gezeigt, was geht, und nicht mit dem ersten. Ein Mittelwert
beschriebe hier eine Belastung, die so nie stattgefunden hat.

Daraus folgt eine Regel mit zwei Fällen:

| Schwerster Satz | Neue Vorgabe |
|---|---|
| **mehr als 10** Wiederholungen | dieses Gewicht, angesetzt auf **10** Wiederholungen |
| **10 oder weniger** | **5 kg weniger**, dafür **15** Wiederholungen |

Aus `15× 25 kg · 15× 30 kg · 15× 35 kg` wird damit **35 kg × 10** — und nicht
ein Wiederholungsziel von 16, das an der Sache vorbeigeht. Die vier Zahlen
(Schwelle, oberes Ziel, unteres Ziel, Abschlag) stehen unter *Mehr →
Trainingsziele* und lassen sich ändern; sie sind eine Trainingsentscheidung,
keine Rechnung, und sollen nachlesbar bleiben.

Liegt das neue Ziel außerhalb der eingestellten Wiederholungsspanne, zieht die
Spanne mit. Sonst stünde „10 Wiederholungen" bei einer Spanne von 12 bis 18 —
und die nächste Fortschreibung rechnete gegen die eigene Vorgabe.

Ein Tippen macht daraus die neue Vorgabe, „Alle übernehmen" erledigt die ganze
Einheit auf einmal.

Ausgewertet wird beim Sync — also das, was gerade hereinkommt. Was davor liegt,
weil die Uhr spät synchronisiert hat, Sätze nachgetragen wurden oder sich die
Regel geändert hat, bliebe sonst für immer unberücksichtigt. Dafür steht unter
*Kraft* der Knopf **„An die letzten Trainings anpassen"**: Er wertet die
gewählte Zeitspanne noch einmal aus. Je Übung bleibt dabei nur der Vorschlag
vom jüngsten Trainingstag offen — die älteren werden als überholt abgelegt,
statt dieselbe Übung dreimal mit drei Zahlen anzubieten. Was abgelehnt wird, bleibt unverändert. Unter *Kraft* steht
außerdem dauerhaft, **was sich seit dem letzten Mal geändert hat** und woraus es
folgte — eine andere Zahl auf dem Zettel ohne Begründung sieht sonst aus wie ein
Fehler.

## Platzhalter sind keine Messwerte

Garmin schreibt `-1` in die Wiederholungszahl, wenn die Uhr nichts zählen
konnte — an Maschinen passiert das ständig. Als Zahl gelesen heißt das nicht
„unbekannt", sondern „minus eine Wiederholung". Die Progression las daraus ein
verfehltes Ziel, hielt das Gewicht und hätte beim zweiten Mal einen **Deload**
ausgelöst: Weil die Uhr nicht zählen konnte, wäre das Gewicht gesunken.

Solche Platzhalter werden jetzt zu der Lücke, die sie sind — beim Import und
zentral in `record_set`, damit auch eine manuelle Eingabe nichts Negatives
hineinschreiben kann. Vorhandene Sätze bereinigt eine Migration beim Start.

Fehlen die Wiederholungen, ist das kein Grund, gar nichts zu tun: Das
**aufgelegte Gewicht** ist bekannt, und damit wird die Vorgabe nachgezogen. Das
gilt auch sonst — wer den Stift umsteckt, hat entschieden. Was tatsächlich
bewegt wurde, ist die Wirklichkeit; die Vorgabe hat ihr zu folgen, nicht
umgekehrt.

## Wann die Waage eine Messung übernimmt

Die Mi Scale meldet ein „stabiles" Gewicht schon, während man noch aufsteigt und
das Gewicht verlagert — stabil im Sinne des Protokolls, aber nicht das, was man
wiegt. Die Impedanz misst sie erst, wenn man wirklich ruhig barfuß steht. Ein
Wert **mit** Impedanz ist deshalb nicht nur vollständiger, er ist auch das
verlässlichere Gewicht.

PULS übernimmt darum nur Messungen, zu denen auch die Impedanz kam — und nimmt
das Gewicht **aus dem Moment, in dem sie kam**, nicht den letzten Frame vor dem
Absteigen. Kommt binnen zwanzig Sekunden keine Impedanz, wird die Messung
verworfen und im Protokoll gesagt, warum.

Wer das nicht will, setzt `REQUIRE_IMPEDANCE=0` — dann kommt das Gewicht auch
allein an, wie früher.

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

Dreiundzwanzig Suiten, alle ohne Netz und gegen Wegwerf-Datenbanken — deine Daten werden
nicht angefasst. Eine davon lässt `deploy.sh` mit einer Docker-Attrappe komplett durchlaufen und
prüft, dass jeder Schritt erreicht wird. Anlass war ein Abbruch mitten im
Deploy, den niemand bemerkte, weil das Skript dabei keinen Fehler meldete.

Eine weitere prüft Eigenschaften, die für die ganze API gelten sollen: dass alle
44 GET-Endpunkte fehlerfrei antworten, dass keiner davon Daten verändert, und
dass zweimal dieselbe Abfrage dasselbe ergibt. Genau dort ist ein Fehler
aufgefallen, den keine einzelne Prüfung gefunden hätte.

Abgedeckt sind ansonsten der Waagen-Parser, das Referenzfenster mit
seiner Kalibrierung, das Ausdünnen der Laufdaten, die Gym-Auswertung, die
Ableitung von Beschwerden bis in den fertigen Trainingsplan, der Garmin-Sync
samt Verlaufs-Import gegen einen nachgebauten Client, die komplette API gegen
die echte Anwendung, und die Frontend-Struktur.

Eine Suite klickt die App in einem **echten Browser** durch — jede Ansicht,
und beim Autopiloten bis zur gespeicherten Auswahl nach dem Neuladen. Anlass war
ein Aufruf, der beim Bearbeiten in einen fremden Klick-Handler gerutscht war:
Der Autopilot wurde dadurch nur noch beim Löschen eines Supplements befüllt, auf
der Seite standen leere Auswahlfelder. Kein Python-Test konnte das sehen, denn
die Datei war syntaktisch einwandfrei und jeder Endpunkt antwortete korrekt.
Sie prüft dabei nicht nur, ob ein Klick ankommt, sondern ob man ihn **sieht**:
Größe und Form der Knöpfe, und ob sich ein ausgewählter Wert farblich abhebt.
Anlass war die Bewertung nach einer Einheit — die Regel für die Zahlenknöpfe
hing an einem Elternteil, den diese Karte nicht hat. Der Klick kam an, der Wert
wurde gespeichert, sichtbar passierte nichts. Für den Nutzer war das Bewerten
damit schlicht kaputt, und kein Test, der nur Zustände prüft, hätte das je
bemerkt.

Diese Suite braucht Playwright und einen Chromium; fehlt beides, überspringt sie
sich, damit sie auf dem Server niemanden aufhält.

Eine prüft die Trends und die zusammengeführte Wochenplanung: Eine vier Wochen
ausgelassene Muskelgruppe muss nach oben rutschen, eine gerade hart trainierte
nach unten, und die geplanten Tage müssen exakt die eingetragenen sein — mit
einem gelegten Effekt (40 s/km schneller bei gleichem Puls), der wiedergefunden
werden muss.

Zwei weitere kamen mit der Statistik dazu. Die eine prüft sie dort, wo sie
wehtut: Zweihundert reine Zufallspaare müssen die Mehrfachprüfung fast
vollständig aussortieren, ein echter Zusammenhang mitten darin muss sie
überstehen. Die andere hält den Garmin-Fehler fest, der Krafteinheiten
unsendbar machte (siehe *Workouts auf der Fenix 7*).

## Installieren und aktualisieren

Das Repository ist **privat**. GitHub antwortet auf einen Download ohne
Anmeldung deshalb mit 404 — ununterscheidbar von „gibt es nicht". Für
`./update.sh` gibt es zwei Wege:

### Weg A — mit Token (Repository bleibt privat)

Einmalig ein Token anlegen: github.com → *Settings* → *Developer settings* →
*Personal access tokens* → **Fine-grained tokens**. Zugriff auf genau dieses
Repository, Berechtigung *Contents: Read-only*. Dann in die `.env`:

```
GITHUB_TOKEN=github_pat_...
```

Ab dann genügt:

```bash
cd /mnt/user/appdata/puls-coach && ./update.sh
```

### Weg B — Repository öffentlich schalten

Im Repository unter *Settings* → *General* → ganz unten *Change repository
visibility*. Danach funktioniert `./update.sh` ohne Token. Im Paket stehen
keine Geheimnisse: Deine `.env` ist per `.gitignore` ausgeschlossen, und
`.env.example` enthält nur leere Platzhalter.

### Wenn beides nicht geht

Auf GitHub *Code → Download ZIP* (im Browser bist du angemeldet), entpacken
und den Inhalt in `/mnt/user/appdata/puls-coach/` spiegeln, dann `./deploy.sh`.

### Was das Skript tut

Es lädt den aktuellen Stand, sichert vorher die Datenbank als
`puls-backup-<Datum>.db` in den Ordner, tauscht **nur die Programmdateien**
aus und startet über `deploy.sh` neu. Deine `.env` bleibt stehen, die Volumes
`puls-data` und `ollama-data` werden nicht angefasst.

| Aufruf | Wirkung |
|---|---|
| `./update.sh` | holen, austauschen, deployen |
| `./update.sh --no-deploy` | nur die Dateien austauschen |
| `PULS_BRANCH=xyz ./update.sh` | einen anderen Branch nehmen |

Wenn etwas klemmt, zeigt `sh -x update.sh` jeden Schritt einzeln.

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
| `./deploy.sh version` | prüft, ob der laufende Container dem Ordner entspricht |
| `./deploy.sh restart` | Container neu starten (bringt **keinen** neuen Code) |
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
2. *Coach*: Ziel hineinschreiben, Gym-Tage und Lauftage anklicken, Dauer setzen.
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

Eine Eigenheit der Garmin-API ist dabei zu beachten, und sie hat PULS schon
einmal die Krafteinheiten unsendbar gemacht: Garmin prüft die **Übungskategorie
gegen die Sportart** des Workouts. Passt eine nicht dazu — etwa eine
Yoga-Stellung, die als ausgleichende Dehnung an eine Krafteinheit gehängt wurde
—, antwortet die API mit `400 – invalid category` und verwirft **das ganze
Workout**, nicht nur den einen Schritt. PULS filtert Kategorien deshalb vor dem
Hochladen gegen die Sportart. Was durchfällt, geht als benannter Zeitblock mit
Dauer und Hinweis mit; die Übung steht also weiter auf der Uhr, nur ohne
Animation.

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
