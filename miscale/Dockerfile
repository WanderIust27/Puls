FROM python:3.12-slim

# Kompletter Bluetooth-Stack im Container: Unraid bringt selbst kein BlueZ mit,
# deshalb starten wir dbus und bluetoothd hier drin. Auf dem Server muss dadurch
# nichts installiert werden — nur der Kernel-Treiber (btusb) muss den Dongle
# erkennen, und der ist in Unraid enthalten.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bluez \
        bluez-tools \
        dbus \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir bleak==0.22.3 httpx==0.27.2

COPY scale_parser.py miscale_service.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
