"""Parser für die BLE-Broadcasts der Xiaomi-Waagen.

Die Waagen funken ihre Messwerte unverschlüsselt als Service Data mit — es muss
nichts gekoppelt werden, wir hören nur passiv zu. Zwei Formate:

  Mi Scale 1  (XMTZC01HM/04HM)  Service-UUID 0x181D, 10 Byte
  Mi Scale 2  (XMTZC05HM/MIBFS) Service-UUID 0x181B, 13 Byte

Layout Mi Scale 2 (13 Byte):
    [0]      Einheit: Bit 0 = lbs, Bit 4 = jin, sonst kg
    [1]      Statusbits: Bit 1 = Impedanz fertig, Bit 5 = Gewicht stabil
    [2:4]    Jahr (little endian), [4] Monat, [5] Tag, [6] Std, [7] Min, [8] Sek
    [9:11]   Impedanz (little endian)
    [11:13]  Gewicht (little endian) — kg: /200, lbs: /100

Nur stabile Messungen werden gemeldet; alles andere ist Zwischenrauschen,
während man noch auf der Waage herumwackelt.
"""
from __future__ import annotations

from typing import Any

UUID_MISCALE_V1 = "0000181d-0000-1000-8000-00805f9b34fb"
UUID_MISCALE_V2 = "0000181b-0000-1000-8000-00805f9b34fb"

LBS_TO_KG = 0.45359237
JIN_TO_KG = 0.5


class ScaleReading(dict):
    """Eine Messung: weight_kg, impedance, stabilized, unit."""


def parse_v2(data: bytes) -> ScaleReading | None:
    """Mi Body Composition Scale 2 (Service Data 0x181B)."""
    if len(data) < 13:
        return None
    ctrl_unit, ctrl_status = data[0], data[1]
    stabilized = bool(ctrl_status & (1 << 5))
    impedance_done = bool(ctrl_status & (1 << 1))

    raw_weight = int.from_bytes(data[11:13], "little")
    impedance = int.from_bytes(data[9:11], "little")

    if ctrl_unit & 0x01:            # lbs
        weight = raw_weight / 100.0 * LBS_TO_KG
        unit = "lbs"
    elif ctrl_unit & 0x10:          # jin (catty)
        weight = raw_weight / 100.0 * JIN_TO_KG
        unit = "jin"
    else:                           # kg
        weight = raw_weight / 200.0
        unit = "kg"

    if not 10.0 < weight < 250.0:   # unplausibel -> verwerfen
        return None
    return ScaleReading(weight_kg=round(weight, 2),
                        impedance=impedance if impedance_done and impedance else None,
                        stabilized=stabilized, unit=unit, version=2)


def parse_v1(data: bytes) -> ScaleReading | None:
    """Mi Scale 1 (Service Data 0x181D) — kann nur Gewicht."""
    if len(data) < 10:
        return None
    ctrl = data[0]
    stabilized = bool(ctrl & (1 << 5))
    raw_weight = int.from_bytes(data[1:3], "little")

    if ctrl & 0x01:
        weight = raw_weight / 100.0 * LBS_TO_KG
        unit = "lbs"
    elif ctrl & 0x10:
        weight = raw_weight / 100.0 * JIN_TO_KG
        unit = "jin"
    else:
        weight = raw_weight / 200.0
        unit = "kg"

    if not 10.0 < weight < 250.0:
        return None
    return ScaleReading(weight_kg=round(weight, 2), impedance=None,
                        stabilized=stabilized, unit=unit, version=1)


def parse_service_data(service_data: dict[str, bytes]) -> ScaleReading | None:
    """Nimmt das service_data eines BLE-Advertisements und liefert die Messung."""
    for uuid, payload in (service_data or {}).items():
        u = str(uuid).lower()
        if u == UUID_MISCALE_V2:
            r = parse_v2(bytes(payload))
            if r:
                return r
        elif u == UUID_MISCALE_V1:
            r = parse_v1(bytes(payload))
            if r:
                return r
    return None


# ------------------------------------------------- Körperzusammensetzung

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def lean_body_mass(weight_kg: float, impedance: int, height_cm: float,
                   age: int) -> float:
    """Magermasse — die Zwischengroesse, auf der alle weiteren Werte aufbauen."""
    lbm = (height_cm * 9.058 / 100.0) * (height_cm / 100.0)
    lbm += weight_kg * 0.32 + 12.226
    lbm -= impedance * 0.0068
    lbm -= age * 0.0542
    return lbm


def _bone_mass(lbm: float, sex_male: bool) -> float:
    """Knochenmasse in kg.

    Achtung: Die Waage misst keine Knochen. Sie misst Gewicht und elektrischen
    Widerstand — alles andere ist gerechnet. Der Wert taugt fuer den Verlauf,
    nicht als medizinische Aussage.
    """
    base = 0.18016894 if sex_male else 0.245691014
    bone = (base - (lbm * 0.05158)) * -1
    bone = bone + 0.1 if bone > 2.2 else bone - 0.1
    return _clamp(bone, 0.5, 8.0)


def _visceral_fat(weight_kg: float, height_cm: float, age: int,
                  sex_male: bool) -> float:
    """Viszeralfett als dimensionslose Kennzahl (unter 10 gilt als unauffaellig)."""
    if sex_male:
        if height_cm < weight_kg * 1.6:
            sub = ((height_cm * 0.4) - (height_cm * (height_cm * 0.0826))) * -1
            vf = ((weight_kg * 305) / (sub + 48)) - 2.9 + (age * 0.15)
        else:
            sub = 0.765 + height_cm * -0.0015
            vf = (((height_cm * 0.143) - (weight_kg * sub)) * -1) + (age * 0.15) - 5.0
    else:
        if weight_kg > (13 - (height_cm * 0.5)) * -1:
            sub = ((height_cm * 1.45) + (height_cm * 0.1158) * height_cm) - 120
            vf = (weight_kg * 500 / sub - 6) + (age * 0.07)
        else:
            sub = 0.691 + (height_cm * -0.0024) + (height_cm * -0.0024)
            vf = (((height_cm * 0.027) - (sub * weight_kg)) * -1) + (age * 0.07) - age
    return _clamp(vf, 1.0, 50.0)


def body_composition(weight_kg: float, impedance: int | None, height_cm: float,
                     age: int, sex: str = "male") -> dict[str, Any]:
    """Koerperwerte aus Gewicht und Impedanz.

    Die Waage funkt nur zwei Dinge: Gewicht und elektrischen Widerstand. Fett,
    Muskeln, Wasser und Knochen sind daraus geschaetzt — die Formeln entsprechen
    denen, die in der Open-Source-Welt fuer die Mi Scale benutzt werden
    (abgeleitet aus dem Verhalten der Hersteller-App). Gut fuer den Trend, nicht
    als absolute Wahrheit. Ohne Impedanz gibt es nur Gewicht und BMI: die
    Impedanz misst die Waage nur bei barfuessigem Kontakt.
    """
    out: dict[str, Any] = {"weight_kg": weight_kg}
    height_m = height_cm / 100.0
    if height_m > 0:
        out["bmi"] = round(weight_kg / (height_m ** 2), 1)
    if not impedance or impedance <= 0 or impedance >= 3000:
        return out

    out["impedance"] = impedance
    male = sex.lower().startswith("m")
    lbm = lean_body_mass(weight_kg, impedance, height_cm, age)
    out["lbm_kg"] = round(lbm, 1)

    if male:
        coefficient = 0.8 if weight_kg < 61 else 1.0
        fat = weight_kg - lbm - (weight_kg * 0.02)
    else:
        coefficient = 0.96 if weight_kg < 50 else 1.0
        fat = weight_kg - lbm

    fat_pct = _clamp(fat / weight_kg * 100 * coefficient, 5.0, 60.0)
    out["body_fat_pct"] = round(fat_pct, 1)

    bone = _bone_mass(lbm, male)
    out["bone_kg"] = round(bone, 2)

    # Muskelmasse jetzt mit echter Knochenschaetzung statt pauschaler 5 %
    muscle = weight_kg - (weight_kg * fat_pct / 100) - bone
    out["muscle_kg"] = round(_clamp(muscle, 10.0, 120.0), 1)

    water = (100 - fat_pct) * 0.7
    water *= 1.02 if water < 50 else 0.98
    out["water_pct"] = round(_clamp(water, 35.0, 75.0), 1)

    out["visceral_fat"] = round(_visceral_fat(weight_kg, height_cm, age, male), 1)
    return out
