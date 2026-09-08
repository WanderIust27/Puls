#!/usr/bin/env bash
# Startet den Bluetooth-Stack im Container und danach den Waagen-Dienst.
set -u

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') START  $*"; }

log "PULS Mi-Scale-Dienst startet …"

# --- 1. Ist überhaupt ein Bluetooth-Adapter da? ------------------------------
if [ -d /sys/class/bluetooth ] && [ -n "$(ls -A /sys/class/bluetooth 2>/dev/null)" ]; then
    log "Bluetooth-Adapter gefunden: $(ls /sys/class/bluetooth | tr '\n' ' ')"
else
    log "FEHLER: Kein Bluetooth-Adapter sichtbar (/sys/class/bluetooth ist leer)."
    log "        Prüfe: Container mit network_mode host und privileged gestartet?"
    log "        Prüfe auf dem Server: lsusb | grep -i blue"
fi

if command -v lsusb >/dev/null 2>&1; then
    USB_BT="$(lsusb 2>/dev/null | grep -iE 'bluetooth|0a12:|8087:|0bda:(8771|b00[0-9])' || true)"
    [ -n "$USB_BT" ] && log "USB-Gerät: $USB_BT"
fi

# --- 2. D-Bus starten (bluetoothd braucht ihn) ------------------------------
mkdir -p /run/dbus
rm -f /run/dbus/pid
dbus-daemon --system --fork 2>/dev/null && log "D-Bus läuft." \
    || log "WARNUNG: D-Bus ließ sich nicht starten."

# --- 3. bluetoothd starten --------------------------------------------------
# --experimental schaltet erweiterte Advertisement-Daten frei, die manche
# Adapter für BLE-Broadcasts brauchen.
/usr/libexec/bluetooth/bluetoothd --experimental >/tmp/bluetoothd.log 2>&1 &
BT_PID=$!
sleep 3

if kill -0 "$BT_PID" 2>/dev/null; then
    log "bluetoothd läuft (PID $BT_PID)."
else
    log "FEHLER: bluetoothd wurde sofort beendet. Log:"
    tail -n 15 /tmp/bluetoothd.log | sed 's/^/        /'
fi

# --- 4. Adapter einschalten -------------------------------------------------
ADAPTER="${HCI_DEVICE:-hci0}"
if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl power on >/dev/null 2>&1 || true
    sleep 1
    STATE="$(bluetoothctl show 2>/dev/null | grep -E 'Powered:|Name:' | tr '\n' ' ')"
    if [ -n "$STATE" ]; then
        log "Adapter-Status: $STATE"
    else
        log "WARNUNG: bluetoothctl meldet keinen Adapter."
    fi
fi

# hciconfig als zweiter Versuch, falls bluetoothctl nicht durchkam
if command -v hciconfig >/dev/null 2>&1; then
    hciconfig "$ADAPTER" up >/dev/null 2>&1 || true
fi

log "Starte Scan-Dienst."
exec python -u miscale_service.py
