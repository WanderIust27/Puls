# PULS — dein lokaler Trainingscoach

Selbstgehosteter Trainingscoach mit lokaler KI (Ollama, rein auf CPU) und
Garmin-Anbindung in beide Richtungen. Läuft komplett auf deinem Server — keine
Cloud-KI, keine Abos.

PULS beantwortet eine Frage: **Was soll ich heute trainieren?** Alles andere
steht dahinter.

## Die vier Reiter

| Reiter | Was dort steht |
|---|---|
| **Plan** | Die Empfehlung für heute, Einheiten auf Zuruf, deine Woche, was geplant ist |
| **Kraft** | Training in Worten nachtragen, neue Gewichte, Muskelgruppen, Übungen |
| **Laufen** | Form und Tempi, Trend, alle Läufe mit Karte und Kurven |
| **Vital** | Erholung, Einschlafzeit, was gerade ausschlägt, sechs Werte mit Erklärung |
| **Gemüt** | Stimmung, Energie, Stress, Beschwerden — und was daraus fürs Training folgt |

Einstellungen stehen nicht als eigener Reiter im Weg, sondern hinter dem Knopf
oben rechts: Ziel, Wochenstruktur, Gewichtssprünge, Garmin, Modell.

---

## Die Empfehlung für heute

Ganz oben im Plan-Reiter steht ein Satz, kein Dashboard. Er entsteht in drei
Schritten, und alle drei sind nachlesbar.

**1. Wie belastbar bist du?** Aus allem, was vorliegt, wird eine Zahl von 0 bis
100:

| Signal | Was gezählt wird |
|---|---|
| Trainingsbereitschaft | der Wert der Uhr, sofern vorhanden |
| Herzratenvariabilität | gegen deine eigene Basislinie, nicht gegen einen Tabellenwert |
| Schlaf | Dauer der letzten Nacht |
| Körperakku | Stand beim Aufwachen |
| Ruhepuls | Abweichung vom Schnitt der letzten vier Wochen |
| Dein Eintrag | Stimmung, Energie, Stress aus dem Gemüt-Reiter |

Jedes Signal hat ein Gewicht; fehlt eines, zählen die übrigen entsprechend
mehr. Die Zahl ist also auch ohne Uhr brauchbar — dann eben aus Schlaf und
deinem eigenen Eintrag. Unter der Empfehlung lässt sich aufklappen, welcher
Messwert welchen Beitrag geliefert hat. Eine Zahl ohne ihre Herkunft ist ein
Orakel.

**2. Was ist offen?** Tage seit dem letzten Krafttraining, Tage seit dem
letzten Lauf, welche Muskelgruppe hinterherhängt, welche Laufart seit Wochen
fehlt, und ob heute nach deiner Wochenstruktur überhaupt ein Trainingstag ist.

**3. Entschieden wird mit Regeln**, in dieser Reihenfolge:

- Belastbarkeit unter 35 → **Pause**, egal welcher Wochentag.
- Unter 52 → höchstens **leicht**, und rund ein Drittel kürzer.
- Über 72 → **hart** erlaubt.
- Liegt die letzte Woche deutlich über dem Schnitt der letzten vier (ACWR über
  1,4), fällt „hart" auf „normal" zurück.
- Schmerz oder Verletzung ab Stufe 3 drosselt auf leicht und nimmt die
  betroffene Muskelgruppe aus dem Schwerpunkt.
- Steht etwas im Plan, geht das vor dem Wochentag.
- Was heute schon stattgefunden hat, steht nicht noch einmal an.

Jede dieser Regeln legt ihren Grund daneben, und die Gründe stehen unter dem
Satz. Der Grundsatz bleibt: **der Code entscheidet, das Modell formuliert.**
Das Modell bekommt die fertige Entscheidung samt Zahlen und fasst sie in zwei
Sätze — es darf sie nicht ändern und keine Zahl nennen, die nicht dasteht. Ist
Ollama nicht erreichbar, steht der gerechnete Satz da. Nüchterner, aber
genauso richtig.

Zur Empfehlung gehört immer die **fertige Einheit**: aufklappen, ansehen, mit
einem Tipp in den Plan legen und von dort an die Uhr schicken.

---

## Ein Training in Worten nachtragen

Das Kernstück des Kraft-Reiters. Du schreibst hin, was du gemacht hast:

> Gestern im Gym: Beinpresse 3×15 mit 60 kg, dann Latzug 12/10/8 bei 45 kg,
> Hamstring-Curls 15 Wdh @ 25 / 30 / 35, Wadenheben stehend 3×20 mit 30 kg
> und Plank 3×60s. Danach 5,2 km in 30 min gelaufen.

Daraus wird:

| gelesen als | Sätze | |
|---|---|---|
| Beinpresse | 15× 60 kg · 15× 60 kg · 15× 60 kg | bekannt |
| Latziehen | 12× 45 kg · 10× 45 kg · 8× 45 kg | bekannt (aus „Latzug") |
| Hamstring-Curls mit Band | 15× 25 kg · 15× 30 kg · 15× 35 kg | bekannt |
| Wadenheben stehend | 20× 30 kg · 20× 30 kg · 20× 30 kg | **neu, wird angelegt** |
| Unterarmstütz | 60 s · 60 s · 60 s | bekannt (aus „Plank") |
| Lauf | 5,2 km in 30 min | als Aktivität |

Erst als Vorschau, zum Abhaken. Erst der zweite Tipp schreibt.

**Was verstanden wird.** Ein paar Schreibweisen für dieselbe Sache:

```
Beinpresse 3x15 mit 60 kg
Beinpresse 3 Sätze à 15 Wdh mit 60 kg
Beinpresse 3x15 60kg
Beinpresse drei Sätze 60 kg 15              → die letzte Zahl sind die Wdh.
Beinpresse 15, 12, 10 mit 60 kg             → drei Sätze mit fallenden Wdh.
Hamstring-Curls 15 Wdh @ 25 / 30 / 35       → drei Sätze mit steigendem Gewicht
Unterarmstütz 3x60s                         → auf Zeit statt auf Wiederholungen
Rückenstrecker 3 mal 15 mit Eigenkörpergewicht
dreimal fünfzehn Beinpresse mit sechzig Kilo
```

Der Trainingstag kommt aus „gestern", „vorgestern", einem Wochentag oder einem
Datum wie „am 9.3."; ohne Angabe ist es heute. Ein Datum ohne Jahr, das in der
Zukunft läge, meint das Vorjahr.

## Wie die Übung wiedergefunden wird

Die erste Fassung verglich Zeichenketten und lag damit spektakulär daneben:
„Rückenstrecker 3 mal 15 **wiederholungen**" kam als *Ausfallschritte* an, denn
deren Alias `lunge` steckt in „wiederho-**lunge**-n". Und „Rudern am Kabelzug"
landete beim Rudergerät, weil dessen Alias `rudern` nun einmal in „rudern
kabelzug" vorkommt. Ein Vergleich, der Wörter mitten in anderen Wörtern findet,
ist für Freitext unbrauchbar.

Verglichen wird jetzt auf Wortebene, mit vier Zutaten:

1. **Wörter zählen unterschiedlich viel.** „Rückenstrecker" kommt einmal in der
   Bibliothek vor und sagt alles; „Gerät" kommt oft vor und sagt wenig.
   Gewichtet wird mit Wortlänge mal Seltenheit.
2. **Es zählt in beide Richtungen.** Was aus deiner Angabe fehlt und was die
   Übung zusätzlich mitbringt. Nur so fällt „Rudern" gegen „Rudern am Kabelzug"
   durch — beide enthalten „Rudern", aber eben nicht nur.
3. **Tippfehler dürfen sein.** „Klimzug" und „Klimmzug" sind dasselbe Wort, und
   „ü" und „ue" sind derselbe Buchstabe — sonst fände „Rückenstrecker" nie den
   Alias `rueckenstrecker`, der genau dafür gedacht war.
4. **Ein genanntes Gerät hat Einspruchsrecht.** Wer „am Kabelzug" schreibt,
   meint nicht die Kurzhantel. Das Gerät entscheidet aber nicht allein — sonst
   gewänne „Crunch am Kabelzug" gegen „Rudern am Kabelzug", weil beide dasselbe
   Gerät nennen. Die Bewegung zählt, das Gerät qualifiziert.

**Bleibt es unklar, fragt PULS das Modell — aus einer geschlossenen Liste.** Es
bekommt deine Schreibweise und bis zu fünf nummerierte Kandidaten aus *deiner*
Bibliothek und antwortet mit einer Zahl, oder mit 0 für „keine davon". Etwas
anderes als eine gültige Zahl gilt als „keine". So kann aus einer Nachfrage
keine erfundene Übung werden. Ist Ollama nicht erreichbar, bleibt der beste
Treffer stehen — dann eben als *unsicher* gekennzeichnet.

**Das letzte Wort hast du.** Jede Zeile der Vorschau hat ein Auswahlfeld mit
den nächstbesten Treffern, der ganzen Bibliothek und „neu anlegen" — auch dann,
wenn die Zuordnung sicher aussieht. Eine falsche Zuordnung, die man nur
abwählen statt richtigstellen kann, kostet mehr als sie spart. Sätze,
Wiederholungen und Gewicht stehen daneben als Zahlenfelder, falls im Text
etwas fehlte.

**Und eine Korrektur bleibt eine Korrektur.** Stellst du „Rückenstrecker" auf
*Rückenstrecken am Boden* um, wird deine Schreibweise zum Alias dieser Übung —
und der anderen weggenommen. Beim nächsten Mal sitzt sie auf Anhieb.

**Gelesen wird mit Regeln, nicht mit dem Modell.** Zahlen sind das Einzige,
worauf es hier ankommt, und ein Sprachmodell, das „60 kg" zu „65 kg" verliest,
ist schlimmer als eines, das gar nichts sagt. Nur wenn die Regeln an einem
Fließtext scheitern, darf das Modell ihn in Zeilen zerlegen — und danach wird
**jede Zahl gegen deinen Originaltext geprüft** und verworfen, wenn sie dort
nicht vorkommt.

Ein Stück Text ohne jede Ziffer („Gestern im Gym") ist Beiwerk und wird
stillschweigend übergangen. Nur was nach Daten aussah und trotzdem nicht
verstanden wurde, landet unter „nicht verstanden" — ein Missverständnis soll
auffallen, ein Füllwort nicht.

Dieselbe Beschreibung zweimal geschickt **ersetzt** den Tag, statt ihn zu
verdoppeln. Sätze, die von der Uhr kamen, bleiben dabei unangetastet.

---

## Wie die Progression funktioniert

Nach jeder Einheit — ob von der Uhr oder nachgetragen — gilt eine Spanne:

> Schaffst du im **schwersten Satz mehr als 12 Wiederholungen**, war das
> Gewicht zu leicht: einen Schritt hoch, Ziel zurück auf **8**.
> Schaffst du **weniger als 8**, war es zu schwer: einen Schritt runter, Ziel
> ebenfalls **8**.
> **Dazwischen sitzt das Gewicht** — dann kommt kein Vorschlag.

Das ist Doppelprogression: Du arbeitest dich innerhalb der Spanne von 8 auf 12
hoch, und oben angekommen geht das Gewicht eine Stufe höher. Die Spanne stellst
du unter *Einstellungen* ein; über den Feldern steht der Satz, den deine Zahlen
gerade ergeben.

Der **Schritt** ist 5 kg, und er ist zugleich das Raster: Ein Vorschlag landet
immer auf einem Vielfachen davon. Wer 47,5 kg gestemmt hat, bekommt 45 oder 50
vorgeschlagen — 47,5 gibt es an keiner Maschine, und eine Vorgabe, die man
nicht einstellen kann, ist keine. Einzige Ausnahme ist die Kettlebell: Die gibt
es in Vierer-Schritten (12, 16, 20, 24), ein Vorschlag von 21 kg wäre eine Zahl
ohne Gewicht dazu. Der Schritt steht bei jeder Übung einzeln und lässt sich
dort ändern — bei leichter Isolationsarbeit wie Seitheben mit 5 kg ist ein
5-kg-Sprung eine Verdopplung, dort lohnt ein kleinerer Wert.

Maßgeblich ist der schwerste Satz des Tages, und darin die meisten
Wiederholungen. Wer sich innerhalb einer Einheit hocharbeitet (25, dann 30,
dann 35 kg), hat mit dem letzten Satz gezeigt, was geht, nicht mit dem ersten.

**Bei unterstützten Übungen dreht sich die Richtung um.** An der
Klimmzugmaschine und am Band ist das Gewicht die *Hilfe*: 60 kg heißt, sie
nimmt dir 60 kg ab. Mehr Kilo sind dort weniger Anstrengung. Solche Übungen
tragen ein Kennzeichen (in der Übungsbibliothek umschaltbar), und dann heißt
*über der Spanne* eben **weniger** Unterstützung. Ohne das Kennzeichen schlüge
PULS nach einem zu schweren Satz „mehr Gewicht" vor und meinte damit „mehr
Hilfe".

**Geändert wird nichts von allein.** Jeder Vorschlag steht mit seinem Beleg da
(„15 Wiederholungen bei 40 kg — mehr als 12, also noch Luft"), nennt die Übung
beim Namen, und ein Tipp macht ihn zur neuen Vorgabe. *Alle übernehmen* geht
auch.

Ein Vorschlag kommt auch dann, wenn die Wiederholungen passen, in der
Bibliothek aber ein anderes Gewicht steht als tatsächlich auf der Maschine lag.
Das ist keine Trainingsänderung, sondern Buchhaltung — und der Text sagt das
auch so.

Der Knopf **An letzte Trainings anpassen** rechnet die letzten drei Wochen neu
durch. Nützlich, wenn ein Sync Sätze nachgeliefert hat, die beim ersten
Durchlauf noch fehlten.

**Platzhalter sind keine Messwerte.** Garmin schreibt `-1` in die
Wiederholungen, wenn die Uhr nicht mitgezählt hat — an Maschinen ständig. Als
Zahl gelesen heißt das nicht „unbekannt", sondern „minus eine Wiederholung":
Die Progression läse daraus ein verfehltes Ziel. Solche Werte werden beim
Einlesen zur Lücke, die sie sind.

**Ein zweiter Eintrag ersetzt den ganzen Tag.** Nicht nur die Übungen, die
diesmal vorkommen. Vorher wurde je Übung ersetzt — wer eine falsche Zuordnung
richtigstellte und noch einmal eintrug, hatte danach beides in der Datenbank:
die neuen Sätze bei der richtigen Übung und die alten bei der falschen. Aus
denen las die Fortschreibung dann ein Gewicht, das zu einer ganz anderen Übung
gehörte. Sätze von der Uhr bleiben dabei unangetastet — die hat niemand
getippt.

## Deine Woche

Gym-Tage und Lauftage klickst du getrennt an, dazu je eine Dauer. Der Rest
folgt daraus: **Woche planen** legt die sieben Tage an, **Alles an die Uhr**
schiebt sie auf die Fenix.

Den Schwerpunkt der Gym-Tage setzt nicht eine feste Aufteilung, sondern der
gerechnete Bedarf: Was vier Wochen zu kurz kam, kommt zuerst. Eine feste
Push/Pull-Rotation gibt es bewusst nicht mehr — sie war eine Antwort auf eine
Frage, die die Trends besser beantworten. Wer trotzdem eine bestimmte Einheit
will, sagt es:

## Einheit auf Zuruf

Ein Satz genügt:

- „90 Minuten Ganzkörper"
- „30 Minuten zuhause mit Fokus auf Bauch und Rumpf"
- „60 Minuten zuhause für den Handstand"
- „Push-Training, 75 Minuten"

Gelesen werden Dauer, Ort, Muskelgruppen und Ziel — mit Regeln, und nur wo die
nichts finden, hilft das Modell aus. Was im Satz eindeutig dasteht (eine Zahl
mit „min"), ist verlässlicher als jede Schätzung und wird nie überschrieben.

Ein **gezielter** Wunsch schrumpft den Auftakt und die Klimmzugarbeit
zugunsten der gewünschten Gruppen: Wer „Sixpack" schreibt, will nicht eine
Bauchübung von sechsen. Ein **breiter** Wunsch („Ganzkörper") bleibt
ausgewogen — dort ist die Gleichverteilung ja gerade der Punkt.

Bei einem Schwerpunkt stehen Matten-Übungen vor den Maschinen: Nach dem
Aufwärmen liegt man ohnehin schon, und die Geräte sind später frei.

---

## Wie lange eine Einheit wirklich dauert

Die Dauer ist gerechnet, nicht behauptet: Arbeitszeit (3,5 s je Wiederholung
oder die vorgegebene Zeit) plus Pausen plus 45 s Gerätewechsel, über alle
Blöcke. Steht das Ergebnis mehr als 7 % neben der gewünschten Zahl, wird die
Zusammenstellung angepasst, bis es passt. Und was die Empfehlung als Dauer
nennt, ist die Dauer der gebauten Einheit — eine Empfehlung, die 75 Minuten
sagt und 80 liefert, ist an genau der Stelle falsch, an der man sie nachrechnet.

---

## Was der Coach aus deinen Läufen liest

Der Laufen-Reiter zeigt Form und Trend nebeneinander:

- **Tempo bei gleichem Puls.** Die aussagekräftigste Zahl im Ausdauertraining:
  nur Läufe über 2 km, nur der Bereich zwischen Puls 120 und 155. Vier Wochen
  gegen die vier davor. Schneller bei gleichem Puls heißt besser — alles
  andere kann auch am Wetter liegen.
- **Umfang, längste Einheit, Anteil harter Läufe.** Fehlt der Tempoanteil ganz,
  steht das Renntempo; sind mehr als 40 % der Läufe hart, ist es zu viel.
- **Bestzeiten** über 1, 5, 10 km und Halbmarathon, auf die Distanz
  hochgerechnet.
- **Jeder Lauf einzeln**: Puls-, Tempo- und Höhenkurve, GPS-Spur auf der Karte,
  Kilometersplits, und eine Bewertung, die sagt, ob der Lauf das war, was er
  sein sollte.

Welche Laufart die Tagesempfehlung vorschlägt, folgt aus demselben Trend: Fehlt
der harte Anteil, kommt ein Tempolauf; ist die längste Einheit geschrumpft und
steht Ausdauer im Ziel, ein langer Lauf; an einem schwachen Tag immer locker.

---

## Schlaf und Vitalwerte

Die Uhr liefert vierzig Zahlen pro Tag. Die meisten sagen einem Menschen
nichts, und eine Zahl, die man nicht einordnen kann, ist keine Information,
sondern Beunruhigung. Der Vital-Reiter zeigt deshalb **sechs**, und jede
bringt drei Dinge mit:

1. **Was sie heute ist** — gegen deine eigene Basislinie der letzten vier
   Wochen, nicht gegen einen Tabellenwert. 52 Schläge Ruhepuls sind für den
   einen hoch und für den anderen niedrig.
2. **Wohin sie sich bewegt** — die letzten sieben Tage gegen die drei Wochen
   davor, mit Pfeil und Prozentwert.
3. **Was sie überhaupt bedeutet.** Ein Satz beim Aufklappen, kein Lehrbuch.

Die sechs sind Schlaf, Herzratenvariabilität, Ruhepuls, Körperakku beim
Aufwachen, Stress am Tag und Atemfrequenz. Die letzte ist der leiseste
Frühwarnwert, den die Uhr hat: Sie steigt oft ein bis zwei Nächte, bevor man
etwas spürt.

**Was gerade ausschlägt** steht obenan — aber höchstens drei. Ausschlag heißt:
mehr als 1,4 Standardabweichungen von deinem eigenen Schnitt entfernt. Darüber
steht ein Satz, der sie zusammen einordnet; liegen drei gleichzeitig daneben,
ist das selten Zufall. Die Bewertung steht dort einmal und nicht hinter jeder
Zeile — sechsmal „das sollte man beobachten" liest niemand zu Ende.

### Wann du ins Bett solltest

    Zubettgehzeit = Aufstehziel − Schlafbedarf − Einschlafdauer

Das **Aufstehziel** stellst du unter *Einstellungen* ein. Der **Schlafbedarf**
ist keine feste Zahl: acht Stunden als Grundlage, plus je eine halbe Stunde bei
schwacher Trainingsbereitschaft, bei einer HRV unter deiner Basislinie und nach
einer langen Einheit, dazu bis zu einer halben Stunde für den Rückstand der
letzten Nächte. **Jeder Zuschlag wird benannt** — eine Zahl, die von acht auf
neuneinhalb springt, ohne dass jemand sagt warum, hält man für einen Fehler.

Die **Einschlafdauer** kommt aus deinen eigenen Nächten (Zeit im Bett minus
tatsächlich geschlafene Zeit), sobald fünf davon vorliegen; vorher gilt ein
Vorgabewert von 15 Minuten, und das steht auch so da.

Daneben steht, wie **regelmäßig** du ins Bett gehst: die typische Uhrzeit und
die Streuung über zwei Wochen. Der Zeitpunkt zählt fast so viel wie die Dauer —
ein Körper, der jeden Abend zu einer anderen Zeit schlafen geht, erholt sich
schlechter als einer mit sieben ruhigen Stunden nach Plan.

## Gemüt und Beschwerden

Stimmung, Energie und Stress auf einer Skala von 1 bis 5, dazu eine Notiz.
Aus der Notiz liest PULS Beschwerden heraus („Knie zwickt seit gestern") und
merkt sich Region, Art und Stärke.

Das ist kein Tagebuch, sondern ein Eingangssignal: Der Eintrag geht in die
Belastbarkeit ein, und eine Beschwerde nimmt die betroffenen Muskelgruppen aus
dem Schwerpunkt. Muskelkater heißt dosieren, Schmerz heißt aussetzen — und
zwar nur so lange, wie er nachwirkt: drei Tage für Muskelkater, vier für
Verspannungen.

Der Verlauf zeigt alle drei Werte an ihren echten Uhrzeiten. Eine Lücke bleibt
eine Lücke: Zwischen zwei Punkten, die weiter auseinanderliegen als üblich,
wird nicht durchgezogen.

---

## Was PULS im Hintergrund weiter tut

Ohne eigenen Reiter, aber weiterhin in Betrieb:

- **Garmin-Sync** alle drei Stunden: Aktivitäten, Detaildaten, Schlaf, HRV,
  Ruhepuls, Körperakku, Stress, Trainingsbereitschaft. Danach werden die
  Gewichtsvorschläge aus den frischen Sätzen abgeleitet, damit sie morgens
  schon dastehen.
- **Die Waage** (Mi Scale 2 über den Nachbarcontainer) schreibt weiter in die
  Datenbank. Angezeigt wird sie nicht mehr — das Gewicht war eine Zahl, die
  täglich schwankte und nichts entschied.
- **Läufe, Schlaf, Herzdaten** bleiben vollständig gespeichert. Was ein
  gelöschter Reiter angezeigt hat, ist nicht gelöscht.

Beim Umbau geht nichts verloren: Die Tabellen bleiben, wie sie sind, und ein
Update trägt nur nach, was fehlt.

---

## Übungsbibliothek

Rund 60 Übungen zum Start, aufgeteilt in Blöcke (Kettlebell-Auftakt,
Klimmzugarbeit, Hauptteil, Matte, Dehnen), jede mit Gewicht, Zielwiederholungen,
Satzzahl, Pausenzeit und ihrer Entsprechung im Garmin-Katalog.

Gesät wird beim ersten Start. Kommen mit einem Update neue Übungen oder neue
Aliase dazu, würde sie sonst niemand sehen, der PULS schon benutzt — deshalb
gleicht PULS beim Hochfahren ab und trägt nach, was fehlt. Aliase, die sich als
zu grob erwiesen haben, werden dabei auch wieder entfernt: `rudern` am
Rudergerät zog jede Rudervariante an sich. Deine Gewichte, Zielwerte, selbst
angelegten Übungen und selbst gelernten Schreibweisen bleiben unberührt.

Für zuhause reicht eine Matte und eine kleine Hantel. Dazu gehören ein eigener
**Aufwärmblock** (Hampelmänner, Armkreise, Hüftkreisen, Beinpendel, Knieheben,
Rumpfdrehen), sechs **Liegestütz-Varianten** vom Knie-Liegestütz bis zur
Negativ-Variante mit erhöhten Füßen, und Mattenarbeit von der Russischen
Drehung über Seitstütz-Varianten bis zu Scherenbeinen.

Jede Übung kann eine **Notiz** tragen, und die steht später in der Einheit
unter der Übung: „beide Seiten nacheinander", „Ellenbogen nah am Körper",
„Hüfte darf nicht wackeln". Beim Seitstütz ist genau das der Unterschied
zwischen einem Satz und einem halben.

Vorher begann jede Zuhause-Einheit mit einer Zeile „3 Minuten aufwärmen". Wer
das liest, macht zwei Schulterkreise und fängt an.

---

## Tests

```bash
./tests/run_all.sh
```

Achtzehn Suiten, alle ohne Netz und gegen Wegwerf-Datenbanken — deine Daten
werden nicht angefasst.

Zwei davon decken die beiden Kernstücke ab. Die eine schickt jede Schreibweise
durch den Textleser und prüft, dass genau die Sätze herauskommen, die
dastehen — dass ein Dezimalkomma keine zwei Läufe macht, dass „15 Wdh @ 25 /
30 / 35" drei Sätze mit steigendem Gewicht sind und nicht drei Wiederholungen,
und dass eine Zahl, die im Originaltext nicht vorkommt, verworfen wird. Ein
ganzer Prüfsatz hält dabei den schwierigen Fall fest, an dem die erste Fassung
gescheitert ist: fünf Übungen in einem Satz, mit Tippfehler, Zahlwörtern, einer
Zahl ohne Einheit und einem Gerät, das widerspricht. Dazu gehört die Probe,
dass „wiederholungen" keine Übung mehr findet. Die
andere stellt die Tagesempfehlung in Lagen, die eine klare Antwort verlangen:
erschöpft am Gym-Tag muss Pause ergeben, erholt am Gym-Tag eine harte Einheit,
ein Knieschmerz muss die Beine aus dem Schwerpunkt nehmen, und was heute schon
stattgefunden hat, darf nicht noch einmal vorgeschlagen werden.

Eine prüft Eigenschaften, die für die ganze API gelten: dass alle GET-Endpunkte
fehlerfrei antworten, dass keiner davon Daten verändert, und dass zweimal
dieselbe Abfrage dasselbe ergibt. Genau dort ist ein Fehler aufgefallen, den
keine einzelne Prüfung gefunden hätte.

Eine Suite klickt die App in einem **echten Browser** durch: jeden Reiter, das
Nachtragen bis zum übernommenen Vorschlag, die geschalteten Wochentage bis über
ein Neuladen hinweg. Sie prüft dabei nicht nur, ob ein Klick ankommt, sondern
ob man ihn **sieht** — Größe der Knöpfe, und ob ein ausgewählter Wert sich
farblich abhebt. Anlass war die Bewertung nach einer Einheit: Die Regel für die
Zahlenknöpfe hing an einem Elternteil, den diese Karte nicht hatte. Der Klick
kam an, sichtbar passierte nichts, und kein Test, der nur Zustände prüft, hätte
das je bemerkt. Beim Umbau hat dieselbe Suite sofort den nächsten Fehler dieser
Art gefunden: `charts.js` benutzte eine Funktion, die in `app.js` stand — die
Diagramme liefen nur, solange zufällig beides zusammenpasste.

Diese Suite braucht Playwright und einen Chromium; fehlt beides, überspringt
sie sich, damit sie auf dem Server niemanden aufhält.

Abgedeckt sind außerdem der Waagen-Parser, das Referenzfenster, das Ausdünnen
der Laufdaten, die Gym-Auswertung, die Ableitung von Beschwerden bis in den
fertigen Trainingsplan, der Garmin-Sync samt Verlaufs-Import gegen einen
nachgebauten Client, der Garmin-Fehler, der Krafteinheiten unsendbar machte
(siehe *Workouts auf der Fenix 7*), die Frontend-Struktur und `deploy.sh` mit
einer Docker-Attrappe.

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
weniger Speicher lieber `qwen3:4b` unter *Einstellungen → Modell*.

### KI-Modell wählen

Das Modell stellst du in der App unter *Einstellungen → Modell* ein — der Download läuft im
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

1. *Einstellungen → Garmin*: verbinden (MFA wird unterstützt, gespeichert werden nur Tokens).
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

1. In PULS unter *Einstellungen* das Token kopieren.
2. In der `docker-compose.yml` bei `miscale` als `PULS_TOKEN` einsetzen, dazu
   `HEIGHT_CM`, `AGE` und `SEX` für die Körperfett-Schätzung.
3. Neu starten: `./deploy.sh`
4. In PULS auf *Einstellungen* gehen — dort siehst du **live**, was passiert.

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
eine openScale-Bridge nach Garmin Connect.

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
- Täglich laufen plus 3× Gym ist ein ordentliches Pensum. Die Tagesempfehlung
  rechnet deine Belastung (ACWR) mit; steigt sie deutlich über den Schnitt der
  letzten vier Wochen, bremst sie von selbst.

## Technik

FastAPI + SQLite (Volume `puls-data`), Ollama als eigener Container, Mi-Scale-Dienst mit
`bleak`, Frontend als abhängigkeitsfreie Vanilla-JS-PWA. Ein einziger
Hintergrundjob: der Garmin-Sync (alle `SYNC_INTERVAL_HOURS`), der danach die
Gewichtsvorschläge aus den frischen Sätzen ableitet.

Diagramme und Karte sind selbst gezeichnetes Inline-SVG — auch die Karte, denn
eine unbewegliche Karte braucht keine Kartenbibliothek: Es genügt, die
Kachelnummern für den Ausschnitt auszurechnen und die Bilder an die richtige
Stelle zu legen. Das sind ein paar Zeilen statt 150 kB Fremdcode.

Der durchgehende Grundsatz: **Der Code rechnet, das Modell formuliert.**
Trainingsgewichte, Tempozonen, 1RM, VO₂max, Progression und die Belastbarkeit
sind deterministisch. Das Modell formuliert und zerlegt — es erfindet keine
Zahlen, und beim Nachtragen wird jede Zahl, die es liefert, gegen deinen
eigenen Text geprüft.

| Env-Variable | Default | Bedeutung |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:8b` | Startmodell (in der App änderbar) |
| `OLLAMA_TIMEOUT` | `600` | max. Antwortzeit in s (CPU!) |
| `SYNC_INTERVAL_HOURS` | `3` | Garmin-Sync-Intervall |
| `SYNC_LOOKBACK_DAYS` | `14` | wie weit zurück gesynct wird |
| `PULS_PORT` | `1337` | Port, unter dem PULS im Browser läuft |
| `PULS_TOKEN` (miscale) | — | Token aus *Einstellungen* |
| `SCALE_MAC` (miscale) | leer | nur auf diese Waage hören |
| `MIN_WEIGHT_KG` (miscale) | `30` | leichtere Messungen ignorieren |

Parser-Tests der Waage: `cd miscale && python3 test_parser.py`
