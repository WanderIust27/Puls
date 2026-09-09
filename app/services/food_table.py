"""Nährwerte je 100 g — die Rechengrundlage für Freitext-Mahlzeiten.

Das Modell darf hier eines: eine Beschreibung in Bestandteile und Mengen
zerlegen ("zwei Eier und ein Vollkornbrot" → Ei 120 g, Vollkornbrot 60 g).
Die Nährwerte kommen dann aus dieser Tabelle, nicht aus dem Modell. Ein
lokales 8B-Modell auf der CPU rechnet Kalorien nicht zuverlässig — es
schätzt sie, und zwar jedes Mal anders. Eine Tabelle schätzt auch, aber
immerhin gleichbleibend und nachschlagbar.

Die Werte sind Durchschnitte gängiger Produkte, gerundet. Sie ersetzen keine
Packungsangabe; wer es genau braucht, trägt die Zahlen von Hand ein.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

log = logging.getLogger("puls.food")

# name: (kcal, Eiweiß g, Kohlenhydrate g, Fett g) je 100 g
# Dazu Synonyme, unter denen dasselbe gefunden wird.
FOODS: dict[str, tuple[tuple[float, float, float, float], tuple[str, ...]]] = {
    # --- Getreide, Brot, Beilagen ---------------------------------------
    "Haferflocken": ((372, 13.5, 58.7, 7.0), ("hafer", "porridge", "oats")),
    "Vollkornbrot": ((215, 7.0, 38.0, 1.9), ("brot", "schwarzbrot", "roggenbrot")),
    "Weißbrot": ((265, 8.5, 49.0, 3.0), ("baguette", "brötchen", "semmel", "toast")),
    "Reis (gekocht)": ((130, 2.7, 28.0, 0.3), ("reis",)),
    "Nudeln (gekocht)": ((158, 5.8, 31.0, 0.9), ("pasta", "spaghetti", "penne")),
    "Kartoffeln (gekocht)": ((87, 2.0, 20.0, 0.1), ("kartoffel", "salzkartoffeln")),
    "Pommes": ((312, 3.4, 41.0, 15.0), ("fritten", "pommes frites")),
    "Couscous (gekocht)": ((112, 3.8, 23.0, 0.2), ("couscous", "bulgur")),
    "Müsli": ((360, 10.0, 60.0, 8.0), ("müsli", "granola", "cerealien")),
    # --- Eiweißquellen ---------------------------------------------------
    "Hähnchenbrust": ((165, 31.0, 0.0, 3.6), ("hähnchen", "huhn", "pute", "geflügel")),
    "Rindfleisch": ((250, 26.0, 0.0, 15.0), ("rind", "steak", "hack", "hackfleisch")),
    "Schweinefleisch": ((242, 27.0, 0.0, 14.0), ("schwein", "kotelett", "schnitzel")),
    "Lachs": ((208, 20.0, 0.0, 13.0), ("lachs", "salmon")),
    "Thunfisch (Dose)": ((116, 26.0, 0.0, 1.0), ("thunfisch", "tuna")),
    "Ei": ((155, 13.0, 1.1, 11.0), ("eier", "spiegelei", "rührei", "omelett")),
    "Magerquark": ((67, 12.0, 4.0, 0.3), ("quark",)),
    "Skyr": ((63, 11.0, 4.0, 0.2), ("skyr",)),
    "Naturjoghurt": ((61, 3.5, 4.7, 3.3), ("joghurt", "jogurt")),
    "Hüttenkäse": ((98, 11.0, 3.4, 4.3), ("hüttenkäse", "cottage")),
    "Käse (Gouda)": ((356, 25.0, 2.2, 27.0), ("käse", "gouda", "emmentaler")),
    "Tofu": ((144, 15.0, 2.0, 8.0), ("tofu",)),
    "Linsen (gekocht)": ((116, 9.0, 20.0, 0.4), ("linsen",)),
    "Kichererbsen (gekocht)": ((139, 7.0, 21.0, 2.6), ("kichererbsen", "hummus")),
    "Bohnen (gekocht)": ((127, 8.7, 22.8, 0.5), ("bohnen", "kidneybohnen")),
    "Proteinpulver": ((375, 80.0, 5.0, 4.0), ("proteinpulver", "whey", "eiweißpulver",
                                              "proteinshake", "shake")),
    # --- Milch und Getränke ----------------------------------------------
    "Milch (1,5 %)": ((47, 3.4, 4.8, 1.5), ("milch",)),
    "Hafermilch": ((45, 0.8, 6.7, 1.5), ("hafermilch", "haferdrink")),
    "Orangensaft": ((45, 0.7, 10.4, 0.2), ("orangensaft", "saft", "apfelsaft")),
    "Cola": ((42, 0.0, 10.6, 0.0), ("cola", "limonade", "limo")),
    "Bier": ((43, 0.5, 3.6, 0.0), ("bier", "pils", "weizen")),
    "Wein": ((83, 0.1, 2.6, 0.0), ("wein", "rotwein", "weißwein")),
    # --- Obst und Gemüse --------------------------------------------------
    "Banane": ((89, 1.1, 23.0, 0.3), ("banane",)),
    "Apfel": ((52, 0.3, 14.0, 0.2), ("apfel",)),
    "Beeren": ((45, 1.0, 8.0, 0.4), ("beeren", "himbeeren", "heidelbeeren",
                                     "erdbeeren")),
    "Gemüse (gemischt)": ((35, 2.0, 5.0, 0.3), ("gemüse", "brokkoli", "karotten",
                                                "paprika", "zucchini", "salat",
                                                "tomaten", "spinat", "gurke")),
    "Avocado": ((160, 2.0, 2.0, 15.0), ("avocado",)),
    # --- Fette, Nüsse, Süßes ----------------------------------------------
    "Olivenöl": ((884, 0.0, 0.0, 100.0), ("öl", "olivenöl", "rapsöl")),
    "Butter": ((717, 0.9, 0.1, 81.0), ("butter", "margarine")),
    "Nüsse": ((607, 20.0, 12.0, 54.0), ("nüsse", "mandeln", "walnüsse", "cashew")),
    "Erdnussbutter": ((588, 25.0, 20.0, 50.0), ("erdnussbutter", "erdnussmus")),
    "Schokolade": ((535, 6.0, 57.0, 30.0), ("schokolade", "schoko", "riegel")),
    "Kuchen": ((370, 5.0, 50.0, 16.0), ("kuchen", "torte", "muffin")),
    "Chips": ((536, 6.6, 50.0, 34.0), ("chips",)),
    "Eiscreme": ((207, 3.5, 24.0, 11.0), ("eis", "eiscreme")),
    # --- Fertiges ---------------------------------------------------------
    "Pizza": ((266, 11.0, 33.0, 10.0), ("pizza",)),
    "Döner": ((215, 15.0, 16.0, 10.0), ("döner", "kebab")),
    "Burger": ((250, 13.0, 20.0, 13.0), ("burger", "hamburger", "cheeseburger")),
    "Pommes mit Currywurst": ((290, 9.0, 25.0, 18.0), ("currywurst", "bratwurst",
                                                       "wurst")),
    "Suppe": ((55, 2.5, 6.0, 2.0), ("suppe", "eintopf")),
}

# Übliche Portionsgrößen in Gramm, wenn nur "eine Banane" dasteht.
PIECE_G = {
    "Ei": 60, "Banane": 120, "Apfel": 150, "Vollkornbrot": 50, "Weißbrot": 40,
    "Pizza": 350, "Döner": 350, "Burger": 220, "Avocado": 150, "Kuchen": 90,
    "Proteinpulver": 30, "Käse (Gouda)": 30, "Butter": 10, "Olivenöl": 10,
}
DEFAULT_PIECE_G = 100


def _norm(text: str) -> str:
    """Kleinschreibung ohne Akzente — damit 'Müsli' und 'muesli' dasselbe sind."""
    low = text.lower().replace("ß", "ss")
    low = low.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    low = unicodedata.normalize("NFKD", low)
    return "".join(c for c in low if not unicodedata.combining(c))


_INDEX: dict[str, str] = {}
for _name, (_vals, _syn) in FOODS.items():
    _INDEX[_norm(_name)] = _name
    for _s in _syn:
        _INDEX.setdefault(_norm(_s), _name)


def lookup(term: str) -> str | None:
    """Den Tabelleneintrag zu einem Begriff finden.

    Erst genau, dann als Wortbestandteil — "hähnchenbrustfilet" soll
    "Hähnchenbrust" treffen, ohne dass jede Schreibweise in der Tabelle steht.
    """
    if not term:
        return None
    key = _norm(term.strip())
    if key in _INDEX:
        return _INDEX[key]
    for word in re.split(r"[\s,/-]+", key):
        if word in _INDEX:
            return _INDEX[word]
    # Längste Teilzeichenkette gewinnt: "vollkornbrot" schlägt "brot"
    hits = [(len(k), v) for k, v in _INDEX.items() if len(k) >= 4 and k in key]
    return max(hits)[1] if hits else None


def nutrients(name: str, grams: float) -> dict[str, Any] | None:
    """Nährwerte einer Menge — None, wenn die Tabelle das nicht kennt."""
    entry = lookup(name)
    if not entry:
        return None
    kcal, protein, carbs, fat = FOODS[entry][0]
    f = max(0.0, float(grams)) / 100
    return {
        "matched": entry, "grams": round(grams, 1),
        "kcal": round(kcal * f), "protein_g": round(protein * f, 1),
        "carbs_g": round(carbs * f, 1), "fat_g": round(fat * f, 1),
    }


def piece_grams(name: str) -> float:
    entry = lookup(name)
    return PIECE_G.get(entry or "", DEFAULT_PIECE_G)


def names() -> list[str]:
    return sorted(FOODS)
