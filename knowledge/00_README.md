# Wissensdatenbank Fitness-Coach

Grundlage für einen KI-Coach, der Trainings- und Ernährungspläne erstellt und berät.
Aufgebaut für einen 23-jährigen, relativ sportlichen Mann — Ziele: Muskelaufbau, Kraft,
Ausdauer, mehr Klimmzüge, 10 km unter 60 min.

Stand: September 2026.

---

## Aufbau

| Datei | Inhalt |
|---|---|
| `01_Grundlagen_Muskelaufbau.md` | Was Muskeln wachsen lässt: Volumen, Intensität, Frequenz, Progression, realistische Raten |
| `02_Training_Gym.md` | Geräte, Übungsauswahl, Splits, fertige Plan-Templates |
| `03_Training_Zuhause_Calisthenics.md` | Ohne Geräte, mit Bändern, Klimmzug-Progression, Matten-Workouts |
| `04_Cardio_Laufen_HIIT.md` | Intensitätszonen, 80/20, HIIT-Protokolle, Laufaufbau, Verletzungsrisiko |
| `05_Ernaehrung_Grundlagen.md` | Energiebilanz, Makros, Protein, Auf-/Abbauphasen, Timing |
| `06_Guenstig_Kochen.md` | Preis pro 100 g Protein, Einkaufsliste, Meal-Prep-Baukasten, Rezeptgerüste |
| `07_Supplemente.md` | Was wirkt, was nicht, Dosierungen, Werbe-Warnsignale |
| `08_Regeneration_Schlaf_Aufwaermen.md` | Aufwärmen, Schlaf, Muskelkater, Deload, Kälte, Dehnen |
| `09_Sixpack_Koerperfett.md` | Bauchmuskeln, Körperfett, warum punktuelles Abnehmen nicht geht |
| `10_Mythen.md` | Verbreitete Falschaussagen mit Korrektur |
| `11_Coach_Playbook.md` | Verhaltensregeln für den Agenten: Intake, Planlogik, Progression, Sicherheit |
| `12_Quellen.md` | Literaturliste mit Einordnung |

---

## Evidenz-Kennzeichnung

Jede Aussage in dieser Datenbank ist mit einer Stufe versehen. Der Coach muss diese Stufe
mitkommunizieren, wenn Nutzer nachfragen — und darf niedrigstufige Aussagen nie als
Tatsache verkaufen.

- **[A] Gut belegt** — mehrere Meta-Analysen oder Positionspapiere von Fachgesellschaften,
  konsistente Ergebnisse.
- **[B] Wahrscheinlich** — einzelne Meta-Analyse oder mehrere RCTs, aber Effektgrößen klein
  oder Studien heterogen.
- **[C] Plausibel/Praxiswissen** — Coaching-Konsens, mechanistisch begründet, aber
  ohne belastbare direkte Evidenz.
- **[D] Umstritten oder widerlegt** — wird oft behauptet, hält der Prüfung nicht stand.

## Grundhaltung

1. **Effektgrößen ehrlich benennen.** Vieles in der Trainingswissenschaft macht 2–5 %
   Unterschied. Konsistenz über Monate macht 100 %. Der Coach optimiert nie Details,
   solange die Basics (Regelmäßigkeit, Progression, Protein, Schlaf) nicht stehen.
2. **Keine Produktempfehlungen ohne Evidenz.** Wenn ein Mittel in Gruppe C/D der
   AIS-Klassifikation liegt, wird das gesagt — auch wenn der Nutzer danach fragt.
3. **Realistische Zeiträume.** Muskelaufbau wird in Monaten und Jahren gemessen, nicht in
   Wochen. Pläne, die "8 kg Muskeln in 8 Wochen" versprechen, sind falsch.
4. **Individualität > Optimum.** Der beste Plan ist der, der durchgehalten wird.
5. **Grenzen.** Der Coach diagnostiziert nicht, behandelt keine Schmerzen und ersetzt bei
   anhaltenden Beschwerden keinen Arzt oder Physiotherapeuten.

## Einsatz mit lokalem Modell

Die Dateien sind bewusst in Abschnitte mit klaren Überschriften geteilt, damit sie sich
gut chunken lassen (Vorschlag: Chunk-Grenze bei `##`, Overlap ~100 Tokens).
`11_Coach_Playbook.md` gehört in den System-Prompt, nicht in den Vektorindex — es enthält
Verhaltensregeln, keine abrufbaren Fakten.
