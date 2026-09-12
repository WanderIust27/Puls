"""Zahlen, die sowohl in der Wissensdatenbank als auch im Code vorkommen.

Sie stehen hier ein einziges Mal. Steht dieselbe Zahl an zwei Stellen, driften
die beiden irgendwann auseinander — und dann widerspricht PULS sich selbst:
Der Text aus der Wissensdatenbank sagt das eine, die gerechnete Empfehlung das
andere, und beides steht in derselben Antwort.

Jede Zahl nennt ihre Quelle. Wer sie aendert, muss auch die Markdown-Datei
aendern, sonst faengt genau das an, was hier verhindert werden soll.
"""
from __future__ import annotations

# --- Laufen ---------------------------------------------------------------
# 04_Cardio_Laufen_HIIT.md: "Kein einzelner Lauf laenger als 110 % des
# laengsten Laufs der letzten 30 Tage." Die verbreitete 10-%-Wochenregel ist
# laut 10_Mythen.md nicht das Entscheidende — der einzelne zu lange Lauf ist es.
LONG_RUN_FACTOR = 1.10
LONG_RUN_WINDOW_DAYS = 30

# 04_Cardio_Laufen_HIIT.md: polarisierte Verteilung, rund 80 % locker.
EASY_SHARE_TARGET = 0.80

# --- Krafttraining --------------------------------------------------------
# 01_Grundlagen_Muskelaufbau.md: 12-20 harte Saetze pro Muskelgruppe und Woche.
# 11_Coach_Playbook.md Schritt 3: Start bei 10-14, ueber 4-6 Wochen auf 16-20.
VOLUME_MIN_SETS = 12
VOLUME_MAX_SETS = 20
VOLUME_START_SETS = 10

# 11_Coach_Playbook.md Schritt 3: "indirekte Saetze zaehlen 0,5".
INDIRECT_SET_WEIGHT = 0.5

# Stagnation: 11_Coach_Playbook.md Abschnitt 5 — faellt die Leistung zwei
# Einheiten in Folge, wird die Ursache geprueft; ohne Steigerung ueber mehrere
# Einheiten wird die Variante gewechselt.
STAGNATION_SESSIONS = 3

# --- Koerpergewicht -------------------------------------------------------
# 05_Ernaehrung_Grundlagen.md und Playbook Abschnitt 5, als Prozent pro Woche.
GAIN_RATE_RANGE = (0.25, 0.5)
LOSS_RATE_RANGE = (0.5, 1.0)

# --- Schlaf ---------------------------------------------------------------
# 08_Regeneration_Schlaf_Aufwaermen.md: 7-9 h fuer Sportler.
SLEEP_TARGET_H = (7.0, 9.0)

# --- Protein --------------------------------------------------------------
# 05_Ernaehrung_Grundlagen.md: 1,6-2,0 g je kg Koerpergewicht.
PROTEIN_PER_KG = (1.6, 2.0)

# Welche Muskelgruppen eine Uebung nebenbei mittraegt.
#
# Die Tabelle exercises kennt nur eine Muskelgruppe je Uebung. Fuer das
# fraktionale Satzvolumen braucht es aber die zweite Reihe: Ein Klimmzug
# belastet den Bizeps, ein Bankdruecken den Trizeps. Ohne diese Zuordnung
# kaeme fuer Arme fast immer null heraus, und PULS empfaehle Armtraining,
# obwohl schon zwoelf Saetze indirekt darauf gingen.
#
# Bewusst grob: Es geht um die Groessenordnung, nicht um Elektromyographie.
INDIRECT_GROUPS: dict[str, tuple[str, ...]] = {
    "back": ("arms",),          # Ziehen belastet den Bizeps
    "chest": ("arms", "shoulders"),
    "shoulders": ("arms",),
    "legs": ("core",),          # freie Kniebeugen und Kreuzheben
    "arms": (),
    "core": (),
    "cardio": (),
}
