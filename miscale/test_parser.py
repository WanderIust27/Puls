"""Tests für den Waagen-Parser — mit echten Beispiel-Frames."""
import sys

from scale_parser import (UUID_MISCALE_V1, UUID_MISCALE_V2, body_composition,
                          parse_service_data, parse_v1, parse_v2)

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


# Mi Scale 2, stabil, mit Impedanz: 54.23 kg, Impedanz 0x001A = 26 -> unplausibel klein,
# nehmen wir realistisch 0x01F4 = 500
frame = bytes([
    0x02,              # Einheit kg
    0xA6,              # Status: Bit5 stabil, Bit1 Impedanz fertig
    0xE7, 0x07,        # Jahr 2023
    0x01, 0x1F, 0x0C, 0x22, 0x1A,   # Monat/Tag/Std/Min/Sek
    0xF4, 0x01,        # Impedanz 500
    0x5E, 0x2A,        # Gewicht 10846 -> /200 = 54.23 kg
])
r = parse_v2(frame)
check("v2 Gewicht", r["weight_kg"], 54.23)
check("v2 stabil", r["stabilized"], True)
check("v2 Impedanz", r["impedance"], 500)
check("v2 Einheit", r["unit"], "kg")

# Instabile Messung (Bit 5 nicht gesetzt)
unstable = bytearray(frame)
unstable[1] = 0x86      # Bit5 aus
r2 = parse_v2(bytes(unstable))
check("v2 instabil erkannt", r2["stabilized"], False)

# lbs-Modus: Bit 0 im ersten Byte, Rohwert /100 * 0.4536
lbs = bytearray(frame)
lbs[0] = 0x03
lbs[11], lbs[12] = (12000).to_bytes(2, "little")   # 120.00 lbs
r3 = parse_v2(bytes(lbs))
check("v2 lbs umgerechnet", r3["weight_kg"], round(120 * 0.45359237, 2), tol=0.02)
check("v2 lbs Einheit", r3["unit"], "lbs")

# Unplausibles Gewicht wird verworfen
bad = bytearray(frame)
bad[11], bad[12] = (100).to_bytes(2, "little")     # 0.5 kg
check("v2 unplausibel verworfen", parse_v2(bytes(bad)) is None, True)

# Mi Scale 1: 10 Byte, Gewicht in Byte 1-2
v1 = bytes([0x22, 0x5E, 0x2A, 0xE7, 0x07, 0x01, 0x1F, 0x0C, 0x22, 0x1A])
r4 = parse_v1(v1)
check("v1 Gewicht", r4["weight_kg"], 54.23)
check("v1 stabil", r4["stabilized"], True)

# Über die Service-Data-Ebene
sd = {UUID_MISCALE_V2: frame}
check("service_data v2", parse_service_data(sd)["weight_kg"], 54.23)
check("service_data v1", parse_service_data({UUID_MISCALE_V1: v1})["weight_kg"], 54.23)
check("service_data fremd", parse_service_data({"0000fe95-0000-1000-8000-00805f9b34fb":
                                                b"\x01\x02"}) is None, True)

# Körperzusammensetzung: plausible Bereiche
comp = body_composition(75.0, 500, 184, 24, "male")
check("BMI", comp["bmi"], round(75 / 1.84 ** 2, 1))
print("   Fett:", comp.get("body_fat_pct"), "% | Muskel:", comp.get("muscle_kg"),
      "kg | Wasser:", comp.get("water_pct"), "%")
check("Fett plausibel", 5 <= comp["body_fat_pct"] <= 45, True)
check("ohne Impedanz nur BMI", "body_fat_pct" not in body_composition(75.0, None, 184, 24), True)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {failures}")
    sys.exit(1)
print("Alle Parser-Tests bestanden.")
