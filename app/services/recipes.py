"""Rezeptsammlung und Auswahl nach Trainingslage.

Die Naehrwerte stehen hier als Daten, nicht als Modellantwort. Ein 8B-Modell
auf CPU wuerde plausibel klingende Zahlen erfinden, und an erfundenen
Naehrwerten laesst sich keine Bilanz fuehren. Das Modell begruendet die
Auswahl — getroffen wird sie im Code.

Ausgelegt auf die Vorgaben aus den Einstellungen: gemischt mit vegetarischem
Schwerpunkt, schnell im Alltag, vieles vorkochbar.

Angaben je Portion, gerundet. Quelle sind die ueblichen Werte der
Bundeslebensmittelschluessel-Tabellen fuer die jeweiligen Zutaten.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting

log = logging.getLogger("puls.recipes")

# tags: veg (vegetarisch), vegan, fisch, fleisch, quick (unter 20 min),
#       mealprep, protein (viel Eiweiss), carbs (viel Kohlenhydrate),
#       recovery (entzuendungshemmend/regenerativ), breakfast, main, snack
RECIPES: list[dict[str, Any]] = [
    dict(id="skyr_beeren", name="Skyr mit Beeren, Haferflocken und Nüssen",
         tags=["veg", "quick", "protein", "breakfast", "recovery"],
         minutes=5, kcal=480, protein=42, carbs=48, fat=13,
         ingredients=["400 g Skyr natur", "150 g gemischte Beeren (auch TK)",
                      "40 g Haferflocken", "20 g Walnüsse", "1 TL Honig"],
         steps=["Skyr in eine Schüssel geben.",
                "Haferflocken und Beeren unterheben, Nüsse grob hacken und darüber.",
                "Mit Honig abschmecken."],
         note="Der schnellste Weg zu 40 g Eiweiß am Morgen. Beeren aus dem "
              "Tiefkühler sind genauso gut und billiger."),
    dict(id="porridge_banane", name="Haferbrei mit Banane und Erdnussmus",
         tags=["veg", "quick", "carbs", "breakfast"],
         minutes=10, kcal=560, protein=18, carbs=78, fat=18,
         ingredients=["80 g Haferflocken", "300 ml Milch", "1 Banane",
                      "1 EL Erdnussmus", "Prise Salz, Zimt"],
         steps=["Haferflocken mit Milch und Salz aufkochen, 5 Minuten quellen lassen.",
                "Banane in Scheiben schneiden und unterrühren.",
                "Erdnussmus daraufgeben, mit Zimt bestreuen."],
         note="Vor einem längeren Lauf gut zwei Stunden vorher — dann sind die "
              "Kohlenhydrate da, wo sie hingehören."),
    dict(id="rührei_vollkorn", name="Rührei mit Vollkornbrot und Tomaten",
         tags=["veg", "quick", "protein", "breakfast"],
         minutes=12, kcal=520, protein=32, carbs=42, fat=24,
         ingredients=["3 Eier", "2 Scheiben Vollkornbrot", "150 g Kirschtomaten",
                      "1 TL Butter", "Schnittlauch, Salz, Pfeffer"],
         steps=["Eier verquirlen, salzen.",
                "Butter in der Pfanne schmelzen, Eier bei mittlerer Hitze "
                "langsam stocken lassen und dabei rühren.",
                "Tomaten halbieren, kurz mitbraten. Mit Brot servieren."],
         note="Bei niedriger Hitze rühren — dann wird es cremig statt gummiartig."),
    dict(id="quark_pancakes", name="Quark-Pancakes",
         tags=["veg", "protein", "breakfast", "mealprep"],
         minutes=20, kcal=540, protein=46, carbs=52, fat=14,
         ingredients=["250 g Magerquark", "2 Eier", "60 g Haferflocken (gemahlen)",
                      "1 TL Backpulver", "100 g Beeren", "1 TL Öl"],
         steps=["Quark, Eier, gemahlene Haferflocken und Backpulver verrühren.",
                "Teig 5 Minuten quellen lassen.",
                "In wenig Öl bei mittlerer Hitze kleine Pfannkuchen backen, "
                "je Seite 2–3 Minuten.",
                "Mit Beeren servieren."],
         note="Machen sich auch am Vorabend gut — kalt am nächsten Morgen "
              "genauso brauchbar."),

    dict(id="linsen_bolognese", name="Linsen-Bolognese mit Vollkornnudeln",
         tags=["vegan", "mealprep", "protein", "carbs", "main"],
         minutes=30, kcal=680, protein=32, carbs=98, fat=14,
         ingredients=["120 g rote Linsen", "100 g Vollkornnudeln (roh)",
                      "400 g passierte Tomaten", "1 Zwiebel", "2 Knoblauchzehen",
                      "1 Karotte", "1 EL Olivenöl", "Oregano, Salz, Pfeffer"],
         steps=["Zwiebel, Knoblauch und Karotte fein würfeln, in Öl anschwitzen.",
                "Linsen und passierte Tomaten dazu, 200 ml Wasser angießen.",
                "20 Minuten köcheln, bis die Linsen weich sind. Würzen.",
                "Nudeln parallel kochen und untermischen."],
         note="Die doppelte Menge lohnt sich — hält drei Tage im Kühlschrank "
              "und schmeckt am zweiten Tag besser."),
    dict(id="kichererbsen_curry", name="Kichererbsen-Curry mit Spinat",
         tags=["vegan", "mealprep", "protein", "main", "recovery"],
         minutes=25, kcal=620, protein=24, carbs=72, fat=22,
         ingredients=["1 Dose Kichererbsen (250 g abgetropft)", "200 ml Kokosmilch",
                      "200 g Blattspinat (auch TK)", "80 g Basmatireis (roh)",
                      "1 Zwiebel", "2 cm Ingwer", "1 EL Currypulver", "1 TL Öl"],
         steps=["Reis aufsetzen.",
                "Zwiebel und Ingwer würfeln, in Öl anbraten, Curry kurz mitrösten.",
                "Kichererbsen und Kokosmilch dazu, 10 Minuten köcheln.",
                "Spinat unterheben, bis er zusammenfällt. Mit Reis servieren."],
         note="Ingwer und Kurkuma im Curry haben in Studien einen kleinen "
              "Effekt auf Muskelkater. Kein Wundermittel, aber es schadet nicht."),
    dict(id="ofengemuese_feta", name="Ofengemüse mit Feta und Kichererbsen",
         tags=["veg", "mealprep", "main"],
         minutes=35, kcal=580, protein=26, carbs=52, fat=28,
         ingredients=["400 g gemischtes Gemüse (Paprika, Zucchini, Süßkartoffel)",
                      "1 Dose Kichererbsen", "100 g Feta", "2 EL Olivenöl",
                      "Rosmarin, Paprikapulver, Salz"],
         steps=["Ofen auf 200 °C vorheizen.",
                "Gemüse in Stücke schneiden, mit abgetropften Kichererbsen, "
                "Öl und Gewürzen auf einem Blech mischen.",
                "25 Minuten backen, Feta zerbröckelt darüber, weitere 5 Minuten."],
         note="Ein Blech, kaum Aufwand, und die Reste sind am nächsten Tag "
              "das Mittagessen."),
    dict(id="haehnchen_reis", name="Hähnchen mit Reis und Brokkoli",
         tags=["fleisch", "mealprep", "protein", "main"],
         minutes=25, kcal=650, protein=52, carbs=68, fat=16,
         ingredients=["200 g Hähnchenbrust", "80 g Reis (roh)", "250 g Brokkoli",
                      "1 EL Sojasoße", "1 TL Sesamöl", "Knoblauch, Ingwer"],
         steps=["Reis aufsetzen.",
                "Hähnchen in Streifen schneiden, scharf anbraten, herausnehmen.",
                "Brokkoliröschen 4 Minuten in derselben Pfanne braten, "
                "Knoblauch und Ingwer dazu.",
                "Hähnchen zurück in die Pfanne, mit Sojasoße ablöschen."],
         note="Der Klassiker nach dem Gym: viel Eiweiß, genug Kohlenhydrate, "
              "in einer halben Stunde fertig."),
    dict(id="lachs_kartoffeln", name="Ofenlachs mit Kartoffeln und Bohnen",
         tags=["fisch", "protein", "main", "recovery"],
         minutes=30, kcal=700, protein=44, carbs=54, fat=32,
         ingredients=["180 g Lachsfilet", "350 g Kartoffeln", "200 g grüne Bohnen",
                      "1 Zitrone", "2 EL Olivenöl", "Dill, Salz"],
         steps=["Kartoffeln vierteln, mit Öl und Salz bei 200 °C 25 Minuten backen.",
                "Nach 12 Minuten Lachs mit auf das Blech, mit Zitrone beträufeln.",
                "Bohnen in Salzwasser 8 Minuten garen."],
         note="Das Omega-3 im Lachs ist der einzige Nährstoff, bei dem der "
              "Entzündungseffekt gut belegt ist. Einmal die Woche lohnt sich."),
    dict(id="bowl_tofu", name="Bowl mit knusprigem Tofu und Süßkartoffel",
         tags=["vegan", "mealprep", "protein", "main"],
         minutes=30, kcal=640, protein=32, carbs=66, fat=26,
         ingredients=["200 g fester Tofu", "300 g Süßkartoffel", "80 g Edamame",
                      "1 EL Sojasoße", "1 EL Sesam", "1 EL Öl", "Limette"],
         steps=["Süßkartoffel würfeln, mit Öl bei 200 °C 25 Minuten backen.",
                "Tofu trocken tupfen, würfeln, in der Pfanne rundherum knusprig "
                "braten, zum Schluss mit Sojasoße ablöschen.",
                "Edamame kurz garen. Alles in einer Schüssel anrichten, "
                "Sesam und Limettensaft darüber."],
         note="Tofu vorher gut trockentupfen — sonst wird er nicht knusprig, "
              "sondern zäh."),
    dict(id="chili_sin_carne", name="Chili sin Carne",
         tags=["vegan", "mealprep", "protein", "carbs", "main"],
         minutes=35, kcal=590, protein=28, carbs=84, fat=12,
         ingredients=["1 Dose Kidneybohnen", "1 Dose Mais", "400 g gehackte Tomaten",
                      "100 g Bulgur", "1 Zwiebel", "1 Paprika", "1 TL Kreuzkümmel",
                      "Chili, Paprikapulver, 1 EL Öl"],
         steps=["Zwiebel und Paprika würfeln, in Öl anbraten.",
                "Gewürze kurz mitrösten, Tomaten, abgetropfte Bohnen und Mais dazu.",
                "Bulgur einrühren, 20 Minuten köcheln lassen."],
         note="Wird in doppelter Menge nicht aufwendiger und ist das beste "
              "Beispiel für ein Gericht, das aufgewärmt besser schmeckt."),
    dict(id="shakshuka", name="Shakshuka mit Fladenbrot",
         tags=["veg", "quick", "protein", "main"],
         minutes=20, kcal=560, protein=28, carbs=52, fat=26,
         ingredients=["3 Eier", "400 g gehackte Tomaten", "1 Paprika", "1 Zwiebel",
                      "1 TL Kreuzkümmel", "Paprikapulver", "1 EL Öl",
                      "1 Fladenbrot"],
         steps=["Zwiebel und Paprika in Öl weich braten, Gewürze mitrösten.",
                "Tomaten dazu, 8 Minuten einkochen lassen.",
                "Drei Mulden formen, Eier hineingleiten lassen, zugedeckt "
                "6–8 Minuten stocken lassen.",
                "Mit Fladenbrot servieren."],
         note="Eine Pfanne, zwanzig Minuten, und abends nach dem Gym "
              "praktisch narrensicher."),
    dict(id="nudelsalat_bohnen", name="Nudelsalat mit weißen Bohnen und Pesto",
         tags=["veg", "mealprep", "protein", "carbs", "main"],
         minutes=20, kcal=620, protein=26, carbs=82, fat=20,
         ingredients=["120 g Vollkornnudeln (roh)", "1 Dose weiße Bohnen",
                      "150 g Kirschtomaten", "2 EL Pesto", "Rucola", "Parmesan"],
         steps=["Nudeln kochen, kalt abschrecken.",
                "Mit abgetropften Bohnen, halbierten Tomaten und Pesto mischen.",
                "Rucola und gehobelten Parmesan darüber."],
         note="Hält zwei Tage und schmeckt kalt — der praktischste "
              "Meal-Prep-Kandidat der Liste."),
    dict(id="omelett_kartoffel", name="Kartoffel-Omelett mit Zwiebeln",
         tags=["veg", "quick", "protein", "main"],
         minutes=20, kcal=540, protein=26, carbs=48, fat=26,
         ingredients=["4 Eier", "300 g gekochte Kartoffeln", "1 Zwiebel",
                      "2 EL Olivenöl", "Petersilie, Salz"],
         steps=["Kartoffeln in Scheiben, Zwiebel in Ringe schneiden, in Öl "
                "goldbraun braten.",
                "Eier verquirlen, salzen, darübergießen.",
                "Bei kleiner Hitze stocken lassen, einmal wenden."],
         note="Die perfekte Verwertung für Kartoffeln vom Vortag."),
    dict(id="wrap_huettenkaese", name="Wrap mit Hüttenkäse und Gemüse",
         tags=["veg", "quick", "protein", "main"],
         minutes=10, kcal=480, protein=34, carbs=46, fat=16,
         ingredients=["2 Vollkorn-Wraps", "200 g Hüttenkäse", "1 Karotte",
                      "1/2 Gurke", "Handvoll Spinat", "Senf, Pfeffer"],
         steps=["Gemüse in feine Streifen schneiden.",
                "Wraps mit Hüttenkäse bestreichen, würzen.",
                "Gemüse daraufgeben, fest einrollen."],
         note="Zehn Minuten, kein Herd, 34 g Eiweiß. Für Abende, an denen "
              "nichts mehr geht."),

    dict(id="reis_pfanne_ei", name="Gebratener Reis mit Ei und Erbsen",
         tags=["veg", "quick", "carbs", "main"],
         minutes=15, kcal=600, protein=24, carbs=84, fat=18,
         ingredients=["200 g gekochter Reis (vom Vortag)", "2 Eier", "100 g Erbsen",
                      "2 Frühlingszwiebeln", "1 EL Sojasoße", "1 EL Öl"],
         steps=["Reis in heißem Öl in der Pfanne verteilen und anbraten.",
                "Erbsen dazu, Eier an den Rand geben und stocken lassen, "
                "dann unterrühren.",
                "Mit Sojasoße abschmecken, Frühlingszwiebeln darüber."],
         note="Kalter Reis vom Vortag ist hier Voraussetzung — frischer Reis "
              "wird matschig."),
    dict(id="pasta_thunfisch", name="Pasta mit Thunfisch und Tomaten",
         tags=["fisch", "quick", "protein", "carbs", "main"],
         minutes=18, kcal=660, protein=42, carbs=88, fat=16,
         ingredients=["120 g Nudeln (roh)", "1 Dose Thunfisch im eigenen Saft",
                      "400 g gehackte Tomaten", "1 Knoblauchzehe", "1 EL Olivenöl",
                      "Kapern, Petersilie"],
         steps=["Nudeln kochen.",
                "Knoblauch in Öl anschwitzen, Tomaten dazu, 10 Minuten einkochen.",
                "Abgetropften Thunfisch und Kapern unterheben.",
                "Mit den Nudeln mischen."],
         note="Nach einem langen Lauf: viele Kohlenhydrate, ordentlich Eiweiß, "
              "in unter zwanzig Minuten auf dem Tisch."),

    dict(id="quark_snack", name="Magerquark mit Honig und Nüssen",
         tags=["veg", "quick", "protein", "snack"],
         minutes=3, kcal=330, protein=34, carbs=22, fat=12,
         ingredients=["250 g Magerquark", "1 TL Honig", "20 g Mandeln", "Zimt"],
         steps=["Quark mit etwas Wasser cremig rühren.",
                "Honig und gehackte Mandeln unterheben."],
         note="Der Klassiker vor dem Schlafen: langsam verdauliches Casein, "
              "das über die Nacht arbeitet."),
    dict(id="shake_banane", name="Banane-Hafer-Shake",
         tags=["veg", "quick", "carbs", "protein", "snack"],
         minutes=5, kcal=420, protein=28, carbs=58, fat=8,
         ingredients=["300 ml Milch", "1 Banane", "30 g Haferflocken",
                      "20 g Eiweißpulver", "1 TL Kakao"],
         steps=["Alles in den Mixer.", "Eine Minute mixen, bis es glatt ist."],
         note="Direkt nach dem Gym, wenn der Appetit noch fehlt — trinken "
              "geht meist, wenn essen noch nicht geht."),
    dict(id="kirschsaft_quark", name="Sauerkirsch-Quark",
         tags=["veg", "quick", "protein", "snack", "recovery"],
         minutes=5, kcal=360, protein=32, carbs=38, fat=6,
         ingredients=["250 g Magerquark", "150 ml Sauerkirschsaft",
                      "20 g Haferflocken"],
         steps=["Quark mit dem Kirschsaft glatt rühren.",
                "Haferflocken unterheben."],
         note="Sauerkirschsaft ist das eine Hausmittel gegen Muskelkater, für "
              "das es belastbare Studien gibt — der Effekt ist klein, aber real."),
]

# Wonach in welcher Lage gesucht wird
GOAL_TAGS = {
    "gym": ["protein"],
    "long_run": ["carbs"],
    "run": ["carbs", "protein"],
    "rest": [],
    "soreness": ["recovery"],
}


def _diet_style() -> list[str]:
    try:
        value = json.loads(get_setting("diet_style", "[]") or "[]")
        return value if isinstance(value, list) else []
    except ValueError:
        return []


def _excluded() -> list[str]:
    raw = (get_setting("diet_exclude", "") or "").lower()
    return [w.strip() for w in raw.replace(";", ",").split(",") if w.strip()]


def _situation(day: str | None = None) -> dict[str, Any]:
    """Was heute trainiert wurde oder geplant ist — und wie es dir geht."""
    day = day or dt.date.today().isoformat()
    with get_db() as db:
        acts = db.execute(
            "SELECT sport, duration_s, distance_m FROM activities "
            "WHERE substr(start_time,1,10)=?", (day,)).fetchall()
        planned = db.execute(
            "SELECT sport FROM planned_workouts WHERE planned_date=?",
            (day,)).fetchall()
        nutrition = db.execute(
            "SELECT kcal, protein_g FROM nutrition_log WHERE day=?", (day,)).fetchone()

    sports = {r["sport"] for r in acts} | {r["sport"] for r in planned}
    long_run = any(r["sport"] == "running" and
                   ((r["distance_m"] or 0) >= 10000 or (r["duration_s"] or 0) >= 3600)
                   for r in acts)

    situation = "rest"
    if "strength" in sports:
        situation = "gym"
    elif long_run:
        situation = "long_run"
    elif "running" in sports:
        situation = "run"

    sore = False
    try:
        from . import mood
        sore = any(c["kind"] in ("soreness", "fatigue")
                   for c in mood.active_complaints())
    except Exception as e:
        log.debug("Befinden nicht verfuegbar: %s", e)

    return {
        "day": day, "situation": situation, "sore": sore,
        "sports": sorted(sports), "long_run": long_run,
        "kcal_today": (nutrition["kcal"] if nutrition else None),
        "protein_today": (nutrition["protein_g"] if nutrition else None),
    }


def _score(recipe: dict[str, Any], want: list[str], style: list[str],
           protein_gap: float | None) -> float:
    score = 0.0
    for tag in want:
        if tag in recipe["tags"]:
            score += 3.0
    # Vorlieben aus den Einstellungen
    if "vegetarian_lean" in style and ("veg" in recipe["tags"] or "vegan" in recipe["tags"]):
        score += 1.5
    if "quick" in style and "quick" in recipe["tags"]:
        score += 1.0
    if "mealprep" in style and "mealprep" in recipe["tags"]:
        score += 1.0
    # Fehlt heute noch viel Eiweiss, zaehlt das mehr als alles andere
    if protein_gap and protein_gap > 30 and "protein" in recipe["tags"]:
        score += 2.0
    if recipe["minutes"] <= 15:
        score += 0.4
    return score


def suggest(day: str | None = None, meal: str | None = None,
            count: int = 3) -> dict[str, Any]:
    """Passende Rezepte zur heutigen Trainingslage."""
    ctx = _situation(day)
    want = list(GOAL_TAGS.get(ctx["situation"], []))
    if ctx["sore"]:
        want.append("recovery")

    style = _diet_style()
    excluded = _excluded()
    target_protein = get_setting("protein_target", "")
    protein_gap = None
    try:
        if target_protein:
            protein_gap = float(target_protein) - float(ctx["protein_today"] or 0)
    except (TypeError, ValueError):
        protein_gap = None

    pool = []
    for r in RECIPES:
        if meal and meal not in r["tags"]:
            continue
        text = (r["name"] + " " + " ".join(r["ingredients"])).lower()
        if any(bad in text for bad in excluded):
            continue
        pool.append(r)

    # Tagesabhaengig mischen, damit nicht jeden Tag dasselbe oben steht —
    # aber mit dem Datum als Startwert, damit es innerhalb eines Tages stabil ist.
    import random
    rnd = random.Random(f"{ctx['day']}-{meal or 'all'}")
    rnd.shuffle(pool)
    ranked = sorted(pool, key=lambda r: -_score(r, want, style, protein_gap))

    reason_parts = {
        "gym": "Heute stand Krafttraining an — Eiweiß hat Vorrang.",
        "long_run": "Nach der langen Einheit stehen die Kohlenhydrate vorn.",
        "run": "Ein Laufttag: Kohlenhydrate auffüllen, Eiweiß nicht vergessen.",
        "rest": "Ruhetag — nichts Besonderes nötig, einfach ordentlich essen.",
    }
    reason = reason_parts.get(ctx["situation"], "")
    if ctx["sore"]:
        reason += " Wegen des gemeldeten Muskelkaters sind regenerative Gerichte dabei."
    if protein_gap and protein_gap > 30:
        reason += f" Bis zu deinem Eiweißziel fehlen heute noch rund {protein_gap:.0f} g."

    return {
        "context": ctx,
        "reason": reason.strip(),
        "recipes": ranked[:count],
        "total": len(pool),
    }


def get(recipe_id: str) -> dict[str, Any] | None:
    return next((r for r in RECIPES if r["id"] == recipe_id), None)


def all_recipes(meal: str | None = None) -> list[dict[str, Any]]:
    return [r for r in RECIPES if not meal or meal in r["tags"]]


def explain(suggestion: dict[str, Any]) -> str:
    """Das Modell die Auswahl begruenden lassen — Zahlen kommen aus dem Code."""
    picks = suggestion["recipes"]
    if not picks:
        return "Keine passenden Rezepte gefunden."
    listing = "; ".join(
        f"{r['name']} ({r['kcal']} kcal, {r['protein']} g Eiweiß, {r['minutes']} min)"
        for r in picks)
    try:
        from .ollama_client import generate
        return generate(
            prompt=(f"Trainingslage heute: {suggestion['reason']}\n"
                    f"Vorgeschlagen wurden: {listing}\n\n"
                    "Schreibe zwei bis drei Sätze, warum das heute passt. "
                    "Nutze nur die genannten Zahlen, erfinde keine. "
                    "Keine Aufzählung, keine Überschrift."),
            system="Du bist ein nüchterner Ernährungscoach. Du schreibst knapp "
                   "und ohne Heilsversprechen.")
    except Exception as e:
        log.debug("Ohne Modell begruendet: %s", e)
        return suggestion["reason"]
