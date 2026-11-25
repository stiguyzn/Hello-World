# Hello-World
A place to keep my ideas and thoughts on what to do next.

## HomeHub: Ring + Blink dashboard for a Fire tablet

A small Python server that gathers your Ring doorbells/cameras and Blink
cameras into one touch dashboard, sized for a Fire HD 8 or HD 10 on the wall.

The tablet only runs a browser. The server runs on any always-on computer on
your home network (a Raspberry Pi works well).

### Try it with demo devices

    python -m homehub               # then open http://<computer-ip>:8080

### Use your real devices

    pip install -r requirements.txt
    python -m homehub --setup ring   # email, password, 2FA code, once
    python -m homehub --setup blink  # email, password, emailed PIN, once
    HOMEHUB_PROVIDERS=ring,blink HOMEHUB_PIN=1234 python -m homehub

Sign-in tokens are saved in `~/.homehub` (change with `HOMEHUB_DATA_DIR`).
`HOMEHUB_PIN` is optional; when set, arming and disarming ask for it.

### On the tablet

Open the address in Silk, or for a proper wall display use a kiosk browser
(for example Fully Kiosk Browser, sideloaded) set to keep the screen on.

### What works

* Camera and doorbell tiles with snapshots (tap to enlarge), battery, last motion
* Arm/disarm Blink systems and cameras; motion on/off for Ring
* Ring floodlight/spotlight cams appear as light switches
* Recent activity (Ring history; Blink shows current motion only)

Ring and Blink have no official public API. This uses community libraries
that can break when either company changes its service. There is no live
video: both vendors stream through their own apps, so the dashboard shows
snapshots, refreshed every minute or on demand.

### Tests

    python -m unittest discover -s tests
