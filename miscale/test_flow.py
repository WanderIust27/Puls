"""Testet den Ablauf einer echten Messung — ohne Bluetooth, mit simulierter Zeit.

Der Fall, der in der Praxis schiefging: Das stabile Gewicht kommt sofort, die
Impedanz erst Sekunden später. Wurde zu früh gesendet, verschluckte die
Sperrfrist die nachgereichten Körperwerte.
"""
import asyncio
import sys
import types

# bleak wird hier nicht gebraucht — Platzhalter, damit der Import durchgeht
sys.modules.setdefault("bleak", types.SimpleNamespace(BleakScanner=object))

import miscale_service as svc

sent: list[dict] = []
failures: list[str] = []


async def fake_send(reading):
    from scale_parser import body_composition
    payload = body_composition(reading["weight_kg"], reading.get("impedance"),
                               svc.HEIGHT_CM, svc.AGE, svc.SEX)
    sent.append(payload)


async def fake_status():
    return None


def check(name, cond, detail=""):
    print(f"{'OK  ' if cond else 'FAIL'} {name}{' — ' + detail if detail else ''}")
    if not cond:
        failures.append(name)


def frame(weight_kg, impedance=None, stabilized=True):
    """Baut ein Mi-Scale-2-Paket, wie es über Bluetooth ankäme."""
    raw = int(round(weight_kg * 200))
    ctrl = 0x20 if stabilized else 0x00          # Bit 5 = Gewicht stabil
    if impedance:
        ctrl |= 0x02                             # Bit 1 = Impedanz fertig
    data = bytes([0x02, ctrl, 0xE7, 0x07, 0x01, 0x1F, 0x0C, 0x22, 0x1A]) \
        + (impedance or 0).to_bytes(2, "little") + raw.to_bytes(2, "little")
    return {svc.UUID_MISCALE_V2: data}


class FakeDevice:
    def __init__(self, mac="C8:47:8C:AA:BB:CC"):
        self.address = mac
        self.name = "MIBFS"


class FakeAdv:
    def __init__(self, service_data):
        self.service_data = service_data
        self.rssi = -60
        self.local_name = "MIBFS"


def reset(now):
    svc._pending = None
    svc._pending_since = 0.0
    svc._last_sent = 0.0
    svc._last_had_impedance = False
    sent.clear()


async def scenario(name, events, expect_sends, expect_last_has_fat,
                   expect_weight=None, require_impedance=None):
    """events: Liste aus (Zeitpunkt in s, service_data)"""
    print(f"\n--- {name} ---")
    clock = {"t": 1000.0}
    svc.time.time = lambda: clock["t"]           # Zeit kontrollieren
    reset(clock["t"])
    if require_impedance is not None:
        svc.REQUIRE_IMPEDANCE = require_impedance

    task = asyncio.create_task(svc.flusher())
    await asyncio.sleep(0.01)

    async def tick_to(t_abs):
        """Simulierte Uhr auf t_abs stellen und den Flusher laufen lassen."""
        clock["t"] = t_abs
        for _ in range(3):
            await asyncio.sleep(svc.POLL_S * 1.5)

    for at, sd in events:
        await tick_to(1000.0 + at)
        svc._detection_callback(FakeDevice(), FakeAdv(sd))
        await tick_to(1000.0 + at)
    # danach Sekunde für Sekunde weiterlaufen lassen
    for extra in range(1, 25):
        await tick_to(1000.0 + events[-1][0] + extra)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    check(f"{name}: Anzahl Meldungen", len(sent) == expect_sends,
          f"{len(sent)} statt {expect_sends}")
    if sent:
        has_fat = "body_fat_pct" in sent[-1]
        check(f"{name}: Körperwerte in der letzten Meldung",
              has_fat == expect_last_has_fat,
              f"Fett={sent[-1].get('body_fat_pct')}")
        if expect_weight is not None:
            check(f"{name}: gemeldetes Gewicht",
                  abs(sent[-1]["weight_kg"] - expect_weight) < 0.01,
                  f"{sent[-1]['weight_kg']} statt {expect_weight}")


async def main():
    svc.send_to_puls = fake_send
    svc.post_status = fake_status
    svc.POLL_S = 0.005
    svc.SETTLE_S = 3
    svc.IMPEDANCE_WAIT_S = 12
    svc.REQUIRE_IMPEDANCE = True
    svc.COOLDOWN_S = 300
    svc.MIN_WEIGHT = 30
    svc.HEIGHT_CM, svc.AGE, svc.SEX = 184, 24, "male"

    # 1. Der Praxisfall: Gewicht sofort, Impedanz erst nach 8 Sekunden.
    await scenario(
        "Impedanz kommt spät",
        [(0, frame(74.8)), (2, frame(74.8)), (8, frame(74.8, impedance=505))],
        expect_sends=1, expect_last_has_fat=True)

    # 2. Ohne Impedanz wird nichts übernommen. Die Waage meldet schon ein
    #    "stabiles" Gewicht, während man noch das Gewicht verlagert — nur wo
    #    auch die Impedanz kam, stand man wirklich ruhig.
    await scenario(
        "Ohne Impedanz wird verworfen",
        [(0, frame(74.8)), (3, frame(74.8)), (6, frame(74.8))],
        expect_sends=0, expect_last_has_fat=False, require_impedance=True)

    # 2b. Wer das nicht will, schaltet es ab — dann wie früher.
    await scenario(
        "Ohne Impedanz, aber ausdrücklich erlaubt",
        [(0, frame(74.8)), (3, frame(74.8)), (6, frame(74.8))],
        expect_sends=1, expect_last_has_fat=False, require_impedance=False)

    # 2c. Der eigentliche Punkt: Beim Draufsteigen meldet die Waage zu wenig,
    #     erst beim ruhigen Stehen stimmt es. Genommen wird der Wert aus dem
    #     Moment der Impedanz, nicht der letzte Frame beim Absteigen.
    await scenario(
        "Gewicht aus dem Impedanz-Moment",
        [(0, frame(72.1)), (2, frame(74.2)), (8, frame(74.8, impedance=505)),
         (10, frame(71.4))],
        expect_sends=1, expect_last_has_fat=True, expect_weight=74.8,
        require_impedance=True)

    # 3. Kommt die Impedanz erst spät, wird eben nur einmal gemeldet — mit
    #    Körperwerten. Früher ging eine Meldung ohne Werte voraus.
    await scenario(
        "Späte Impedanz, eine saubere Meldung",
        [(0, frame(74.8)), (14, frame(74.8)), (16, frame(74.8, impedance=505))],
        expect_sends=1, expect_last_has_fat=True, require_impedance=True)

    # 3b. Mit erlaubter Meldung ohne Impedanz muss das Nachreichen weiter
    #     funktionieren — die Sperrfrist darf die Körperwerte nicht schlucken.
    await scenario(
        "Nachreichen trotz Sperrfrist",
        [(0, frame(74.8)), (14, frame(74.8)), (16, frame(74.8, impedance=505))],
        expect_sends=2, expect_last_has_fat=True, require_impedance=False)

    # 4. Zweite echte Messung kurz danach wird unterdrückt (Sperrfrist wirkt noch).
    await scenario(
        "Doppelmessung wird unterdrückt",
        [(0, frame(74.8, impedance=505)), (20, frame(74.9, impedance=505))],
        expect_sends=1, expect_last_has_fat=True, require_impedance=True)

    # 5. Wackelige Werte ohne Stabil-Bit werden ignoriert.
    await scenario(
        "Instabile Werte ignoriert",
        [(0, frame(30.1, stabilized=False)), (1, frame(52.0, stabilized=False))],
        expect_sends=0, expect_last_has_fat=False)

    print()
    if failures:
        print(f"{len(failures)} Test(s) fehlgeschlagen: {failures}")
        sys.exit(1)
    print("Alle Ablauf-Tests bestanden.")


asyncio.run(main())
