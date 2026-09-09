"""Lauscht per Bluetooth auf die Mi Scale und meldet Messungen an PULS.

Es wird nichts gekoppelt — die Waage funkt ihre Werte offen, wir hören nur mit.

Ablauf einer Messung: Man stellt sich drauf, die Waage funkt sekündlich
schwankende Werte, am Ende kommt das Stabil-Bit. Wir warten auf das stabile
Gewicht, sammeln kurz weiter (die Impedanz kommt oft 1-2 s später) und melden
dann einen Wert. Danach eine Sperrfrist gegen Doppelmeldungen.

Zusätzlich meldet der Dienst regelmäßig seinen Zustand an PULS, damit sich die
Einrichtung live auf der Website verfolgen lässt.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import time
from typing import Any

import httpx
from bleak import BleakScanner

from scale_parser import (UUID_MISCALE_V1, UUID_MISCALE_V2, body_composition,
                          parse_service_data)

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)-5s %(message)s")
log = logging.getLogger("miscale")

PULS_URL = os.environ.get("PULS_URL", "http://localhost:1337").rstrip("/")
PULS_TOKEN = os.environ.get("PULS_TOKEN", "")
SCALE_MAC = (os.environ.get("SCALE_MAC", "") or "").upper()
MIN_WEIGHT = float(os.environ.get("MIN_WEIGHT_KG", "30"))
COOLDOWN_S = int(os.environ.get("COOLDOWN_S", "300"))
SETTLE_S = float(os.environ.get("SETTLE_S", "3"))
# Wie lange auf die Impedanz gewartet wird, bevor nur das Gewicht gemeldet wird.
# Die Mi Scale misst sie erst, wenn man barfuß ein paar Sekunden stillsteht.
IMPEDANCE_WAIT_S = float(os.environ.get("IMPEDANCE_WAIT_S", "20"))
# Nur Messungen uebernehmen, zu denen auch die Impedanz kam.
#
# Die Waage meldet das Gewicht schon, waehrend man sich noch daraufstellt und
# das Gewicht verlagert — diese fruehen Werte sind zwar "stabil" im Sinne des
# Protokolls, aber nicht das, was man wiegt. Die Impedanz misst sie erst, wenn
# man wirklich ruhig barfuss steht. Ein Wert MIT Impedanz ist deshalb nicht nur
# vollstaendiger, er ist auch das verlaesslichere Gewicht.
REQUIRE_IMPEDANCE = os.environ.get("REQUIRE_IMPEDANCE", "1") not in ("0", "false", "no")
STATUS_INTERVAL_S = int(os.environ.get("STATUS_INTERVAL_S", "10"))
# Takt, in dem geprüft wird, ob eine Messung reif zum Senden ist.
# Nur für Tests interessant — dort wird er heruntergesetzt.
POLL_S = 1.0

HEIGHT_CM = float(os.environ.get("HEIGHT_CM", "180"))
AGE = int(os.environ.get("AGE", "25"))
SEX = os.environ.get("SEX", "male")

SCALE_UUIDS = {UUID_MISCALE_V1, UUID_MISCALE_V2}

_last_sent = 0.0
_last_had_impedance = False
_pending: dict[str, Any] | None = None
_pending_since = 0.0
_started = time.time()

# Was der Dienst zuletzt gesehen hat — Grundlage der Live-Anzeige
_seen: dict[str, dict[str, Any]] = {}      # MAC -> Infos
_stats = {"advertisements": 0, "scale_frames": 0, "measurements": 0,
          "last_error": None, "scanning": False}


def _adapter_info() -> dict[str, Any]:
    """Liest den Adapter direkt aus dem Sysfs — ohne Umweg über bluetoothctl."""
    info: dict[str, Any] = {"present": False, "name": None, "address": None}
    base = "/sys/class/bluetooth"
    try:
        adapters = sorted(os.listdir(base))
    except OSError:
        return info
    if not adapters:
        return info
    info["present"] = True
    info["name"] = adapters[0]
    info["all"] = adapters
    try:
        with open(f"{base}/{adapters[0]}/address") as f:
            info["address"] = f.read().strip()
    except OSError:
        pass
    return info


async def post_status() -> None:
    """Zustand an PULS melden, damit die Website ihn live anzeigen kann."""
    devices = sorted(_seen.values(), key=lambda d: d.get("last_seen", 0), reverse=True)
    payload = {
        "adapter": _adapter_info(),
        "scanning": _stats["scanning"],
        "uptime_s": int(time.time() - _started),
        "advertisements": _stats["advertisements"],
        "scale_frames": _stats["scale_frames"],
        "measurements": _stats["measurements"],
        "last_error": _stats["last_error"],
        "cooldown_active": max(0, int(COOLDOWN_S - (time.time() - _last_sent)))
                           if _last_sent else 0,
        "filter_mac": SCALE_MAC or None,
        "devices": [
            {**d, "seconds_ago": int(time.time() - d.get("last_seen", 0))}
            for d in devices[:20]
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{PULS_URL}/api/scale/report", json=payload,
                              headers={"X-Puls-Token": PULS_TOKEN})
    except httpx.HTTPError as e:
        log.debug("Statusmeldung fehlgeschlagen: %s", e)


async def send_to_puls(reading: dict[str, Any]) -> None:
    payload = body_composition(reading["weight_kg"], reading.get("impedance"),
                               HEIGHT_CM, AGE, SEX)
    payload["source"] = "miscale"
    if reading.get("impedance"):
        payload["impedance"] = reading["impedance"]
    # Der Messzeitpunkt entscheidet, ob die Messung ins Referenzfenster faellt —
    # ohne ihn kann PULS Morgen- und Abendwerte nicht auseinanderhalten.
    payload["measured_at"] = dt.datetime.now().isoformat(timespec="seconds")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{PULS_URL}/api/body/webhook", json=payload,
                                  headers={"X-Puls-Token": PULS_TOKEN})
            if r.status_code >= 400:
                _stats["last_error"] = f"PULS antwortete {r.status_code}: {r.text[:120]}"
                log.error("PULS lehnte die Messung ab (%s): %s", r.status_code, r.text[:200])
            else:
                _stats["measurements"] += 1
                _stats["last_error"] = None
                extra = f", {payload['body_fat_pct']} % Fett" if payload.get("body_fat_pct") else ""
                log.info("Gemeldet: %s kg%s", payload["weight_kg"], extra)
    except httpx.HTTPError as e:
        _stats["last_error"] = f"PULS nicht erreichbar: {e}"
        log.error("PULS nicht erreichbar: %s", e)


def _detection_callback(device, advertisement_data) -> None:
    global _pending, _pending_since
    _stats["advertisements"] += 1
    mac = str(device.address).upper()

    service_uuids = {str(u).lower() for u in (advertisement_data.service_data or {})}
    looks_like_scale = bool(service_uuids & SCALE_UUIDS)

    entry = _seen.get(mac) or {"mac": mac, "count": 0}
    entry["name"] = device.name or advertisement_data.local_name or None
    entry["rssi"] = advertisement_data.rssi
    entry["last_seen"] = time.time()
    entry["count"] = entry.get("count", 0) + 1
    entry["is_scale"] = looks_like_scale
    _seen[mac] = entry

    if not looks_like_scale:
        return

    reading = parse_service_data(advertisement_data.service_data)
    if not reading:
        return
    _stats["scale_frames"] += 1
    entry["last_weight"] = reading["weight_kg"]
    entry["stabilized"] = reading["stabilized"]

    log.debug("%s -> %s kg, stabil=%s, Impedanz=%s, RSSI %s", mac,
              reading["weight_kg"], reading["stabilized"],
              reading.get("impedance"), advertisement_data.rssi)

    if SCALE_MAC and mac != SCALE_MAC:
        return
    if reading["weight_kg"] < MIN_WEIGHT:
        return
    if not reading["stabilized"]:
        return

    now = time.time()
    if _pending is None:
        _pending = dict(reading)
        _pending_since = now
        log.info("Stabile Messung: %s kg — warte bis zu %.0f s auf die Impedanz "
                 "(barfuß stehen bleiben) …", reading["weight_kg"], IMPEDANCE_WAIT_S)
    else:
        if reading.get("impedance") and not _pending.get("impedance"):
            _pending["impedance"] = reading["impedance"]
            log.info("Impedanz empfangen (%s) — Körperwerte können berechnet werden.",
                     reading["impedance"])
        _pending["weight_kg"] = reading["weight_kg"]
        # Das Gewicht aus dem Moment festhalten, in dem die Impedanz vorlag:
        # Dann stand man ruhig. Spaetere Frames koennen wieder wackeln, weil
        # man sich schon zum Absteigen bewegt.
        if reading.get("impedance"):
            _pending["weight_at_impedance"] = reading["weight_kg"]


async def flusher() -> None:
    """Entscheidet, wann eine Messung reif zum Senden ist.

    Die Waage meldet das stabile Gewicht sofort, die Impedanz (und damit alles,
    was Körperfett und Muskelmasse ausmacht) erst ein paar Sekunden später —
    sie misst weiter, solange man barfuß stillsteht. Deshalb:

      * Ohne Impedanz warten wir bis IMPEDANCE_WAIT_S, bevor wir aufgeben.
      * Mit Impedanz genügt das kurze Ruhefenster SETTLE_S.
      * Kommt die Impedanz erst nach dem Senden, darf sie die eben gemeldete
        Messung noch ergänzen — die Sperrfrist gilt dafür nicht.
    """
    global _pending, _last_sent, _last_had_impedance
    while True:
        await asyncio.sleep(POLL_S)
        if _pending is None:
            continue

        age = time.time() - _pending_since
        has_imp = bool(_pending.get("impedance"))

        if has_imp:
            if age < SETTLE_S:
                continue
        else:
            # Noch keine Impedanz: Geduld haben, sie kommt oft erst spät.
            if age < IMPEDANCE_WAIT_S:
                continue
            if REQUIRE_IMPEDANCE:
                log.info("Keine Impedanz nach %.0f s — Messung (%s kg) verworfen. "
                         "Barfuß und ein paar Sekunden ruhig stehen; erst dann "
                         "misst die Waage Fettanteil und Co. — und erst dann "
                         "steht auch das Gewicht wirklich fest. "
                         "(REQUIRE_IMPEDANCE=0 nimmt das Gewicht auch ohne.)",
                         IMPEDANCE_WAIT_S, _pending.get("weight_kg"))
                _pending = None
                _stats["discarded_no_impedance"] = \
                    _stats.get("discarded_no_impedance", 0) + 1
                continue
            log.info("Keine Impedanz nach %.0f s — melde nur das Gewicht. "
                     "(Barfuß und stillstehen liefert die Körperwerte.)",
                     IMPEDANCE_WAIT_S)

        reading, _pending = _pending, None
        # Das Gewicht aus dem Impedanz-Moment schlaegt jeden spaeteren Frame:
        # Da stand man ruhig, danach bewegt man sich schon zum Absteigen.
        settled = reading.pop("weight_at_impedance", None)
        if settled is not None and settled != reading["weight_kg"]:
            log.info("Gewicht aus dem Impedanz-Moment genommen: %s kg statt %s kg.",
                     settled, reading["weight_kg"])
            reading["weight_kg"] = settled

        # Nachreichen erlauben: Wenn wir eben ohne Impedanz gemeldet haben und
        # jetzt eine MIT Impedanz vorliegt, ist das eine Ergänzung, keine neue
        # Messung — die Sperrfrist darf sie nicht verschlucken.
        upgrade = has_imp and not _last_had_impedance
        in_cooldown = bool(_last_sent) and (time.time() - _last_sent) < COOLDOWN_S

        if in_cooldown and not upgrade:
            log.debug("Messung verworfen (Sperrfrist läuft): %s kg",
                      reading["weight_kg"])
            continue
        if upgrade and in_cooldown:
            log.info("Impedanz nachgereicht — ergänze die eben gemeldete Messung.")

        _last_sent = time.time()
        _last_had_impedance = has_imp
        await send_to_puls(reading)
        await post_status()


async def status_loop() -> None:
    while True:
        await post_status()
        await asyncio.sleep(STATUS_INTERVAL_S)


async def main() -> None:
    if not PULS_TOKEN:
        log.warning("PULS_TOKEN ist leer — PULS wird alles ablehnen. "
                    "Token steht in der App unter Mehr → Waage.")
    adapter = _adapter_info()
    if adapter["present"]:
        log.info("Adapter %s (%s) bereit.", adapter["name"], adapter["address"])
    else:
        log.error("Kein Bluetooth-Adapter sichtbar — Scan wird nicht funktionieren.")

    log.info("Suche nach Mi Scale%s. PULS: %s",
             f" mit MAC {SCALE_MAC}" if SCALE_MAC else " (jede in Reichweite)", PULS_URL)

    asyncio.create_task(flusher())
    asyncio.create_task(status_loop())

    while True:
        try:
            scanner = BleakScanner(detection_callback=_detection_callback)
            await scanner.start()
            _stats["scanning"] = True
            _stats["last_error"] = None
            log.info("Scan läuft.")
            while True:
                await asyncio.sleep(60)
                # Geräte vergessen, die lange nichts mehr gefunkt haben
                cutoff = time.time() - 600
                for mac in [m for m, d in _seen.items()
                            if d.get("last_seen", 0) < cutoff and not d.get("is_scale")]:
                    _seen.pop(mac, None)
        except Exception as e:
            _stats["scanning"] = False
            _stats["last_error"] = str(e)
            log.error("Bluetooth-Scan abgebrochen (%s) — neuer Versuch in 30 s", e)
            await post_status()
            await asyncio.sleep(30)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
