# Ghost Controller — Field Test Install Guide

> **Already installed?** See [UPDATING.md](UPDATING.md) to get the latest version.

Ghost Controller is the UAV ground control station for the field test.
Pick your platform below.

---

## A. Laptop / desktop (x86_64 Linux) — recommended

**One-line install** (downloads the AppImage, sets up a **Desktop icon** + menu entry):

```bash
curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
```

**Or manual** — the AppImage is self-contained: no install, no dependencies.

```bash
# 1. Download both files from the release page
#    https://github.com/Sai-Tolle/Ghost-Controller-/releases/latest
#    - Ghost_Controller-x86_64.AppImage
#    - Ghost_Controller-x86_64.AppImage.zsync   (auto-update metadata)
#    Put them in the same folder, e.g. ~/Applications/

# 2. Make it executable and run
chmod +x ~/Applications/Ghost_Controller-x86_64.AppImage
~/Applications/Ghost_Controller-x86_64.AppImage
```

Optional — add it to your app menu:

```bash
cat > ~/.local/share/applications/ghost-handler.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec=/full/path/to/Ghost_Controller-x86_64.AppImage
Icon=ghost-handler
Categories=Utility;
Terminal=false
EOF
```

Optional — add a **Desktop icon** (double-click to launch):

```bash
cat > ~/Desktop/ghost-controller.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec=/full/path/to/Ghost_Controller-x86_64.AppImage
Icon=/full/path/to/icon-256.png
Categories=Utility;
Terminal=false
EOF
chmod +x ~/Desktop/ghost-controller.desktop
```

On GNOME/Ubuntu you may also need to right-click the Desktop icon →
**Allow Launching** the first time.

**Updates:** the app does not update itself. To get a new release, run the
installer again — it downloads the latest AppImage, verifies its SHA-256
checksum and replaces the old one (your settings in `~/.config/Ghost Handler/`
and cached map tiles are kept):

```bash
curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
```

Your version is shown at the bottom of the **GHOST CONTROLLER ▾** menu. The
AppImage also embeds an AppImageUpdate feed, so delta updates work if you have
that tool:

```bash
appimageupdatetool ~/Applications/Ghost_Controller-x86_64.AppImage
```

On a Raspberry Pi (source install) the same installer command updates the
checkout (`git pull`) and its Python dependencies, keeping `backend/gcs.env`.

**Not on your distro's list?** Any x86_64 Linux with glibc 2.35 or newer
works (Ubuntu 22.04+, Debian 12+, current Fedora, Arch…). Testers on Windows/macOS: use a laptop
with Ubuntu live USB instead — this build is Linux-only.

---

## B. Raspberry Pi 5 (aarch64)

Since v0.1.3 there IS an ARM64 AppImage on the release page, but the
recommended Pi path is still running **from source** via the installer below —
it works on any Trixie-based Pi OS without AppImage/FUSE caveats. (Want the
AppImage instead? Grab `Ghost_Controller-aarch64.AppImage` from the
releases page; it needs a Trixie-based OS plus `libfuse2`, or run it with
`APPIMAGE_EXTRACT_AND_RUN=1`.) The Pi must be on **Raspberry Pi OS
64-bit (Bookworm or newer)** — Pi 5 recommended, Pi 4 minimum.

The heavy dependencies (Qt/PySide6, numpy, PyAV, OpenCV) have **no pip
wheels for ARM64** — pip would try to compile them from source (hours).
They come from `apt` instead; pip only installs the pure-Python remainder.

Run first:

sudo apt full-upgrade
**One-line setup** (same steps as below, automated):

```bash
curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
```

The installer sets up a **Ghost Controller icon on the Desktop** —
double-click it to launch. (It also drops a `launch-ghost.sh` in the
repo folder; you can run that from a terminal too.)

**Or manual** (step 1 — system packages: Qt, QML modules, video libs, build tools):

```bash
# 1. System packages (Qt, QML modules, video libs, build tools)
#    NOTE: python3-pyside6.qtquick does NOT include the QML modules the app
#    imports (QtQuick.Controls/Layouts/Dialogs) — Debian splits each into its
#    own qml6-module-* package. Missing these causes "QtQuick.Controls is not
#    installed" on launch.
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv \
    python3-pyside6.qtquick python3-pyside6.qtwidgets \
    python3-numpy python3-av python3-opencv \
    qml6-module-qtquick qml6-module-qtquick-controls \
    qml6-module-qtquick-layouts qml6-module-qtquick-dialogs \
    qml6-module-qtquick-templates qml6-module-qtquick-shapes \
    qml6-module-qtquick-window qml6-module-qtqml-workerscript \
    libgl1 libegl1

# 2. Get the source
git clone https://github.com/Sai-Tolle/Ghost-Controller-.git
cd Ghost-Controller-

# 3. Python dependencies — skip the apt-provided ones (no ARM64 wheels)
python3 -m venv --system-site-packages .venv
grep -vE '^(PySide6|numpy|av==|opencv)' requirements.txt \
    | .venv/bin/pip install -r /dev/stdin

# 4. Run
.venv/bin/python main.py
```

To get a **Desktop icon** when installing manually:

```bash
cat > ~/Desktop/ghost-controller.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec=$HOME/Ghost-Controller-/.venv/bin/python $HOME/Ghost-Controller-/main.py
Icon=/full/path/to/icon-256.png
Categories=Utility;
Terminal=false
EOF
chmod +x ~/Desktop/ghost-controller.desktop
```

`--system-site-packages` is required: it lets the venv see the apt-installed
PySide6 / numpy / PyAV / OpenCV while pip installs the rest (pymavlink,
pyserial, python-dotenv — all pure-Python or with ARM64 wheels, verified).

**No `python3-pyside6` package?** (older Bookworm images) — `sudo apt
full-upgrade` to the Trixie-based release first, or ask us for a
pre-built ARM64 package.

### Serial / telemetry permissions on the Pi

USB telemetry radios and UARTs need group `dialout`. Copy this line
**exactly as written** — `$USER` is not a placeholder, the shell replaces it
with your username (do not type `$USER$` or `<username>`):

```bash
sudo usermod -aG dialout $USER
```

Then **reboot** (or log out and back in) — the new group only applies to new
logins. Check with `groups`: the list must contain `dialout`. The default
user made by Raspberry Pi Imager is usually already in it.

### Using the Pi's GPIO UART (flight controller wired to pins 8/10)

1. `sudo raspi-config` → *Interface Options* → *Serial Port*:
   "login shell over serial?" **No**, "serial port hardware enabled?" **Yes**,
   then reboot. If the login shell stays on, it owns the UART and MAVLink never
   gets through (Ghost Controller's Auto mode skips the UART in that case).
2. Use **`/dev/serial0`**, not `/dev/ttyAMA0`: on Pi 3/4 `ttyAMA0` is wired to
   Bluetooth and the GPIO pins are `ttyS0`; `serial0` always points at the
   right one.
3. Wire TX→RX and RX→TX, common GND, and set the flight controller port to
   MAVLink at the same baud (ArduPilot `SERIALx_PROTOCOL=2`, `SERIALx_BAUD=57`
   for 57600; PX4 `MAV_x_CONFIG` + `SER_TELx_BAUD`).

---

## C. Connecting to the drone (both platforms)

1. Launch Ghost Controller — it starts **DISCONNECTED** (never fakes a link).
2. The HUD shows the configured listening address. Common setups:

| Link | Setting |
|------|---------|
| Wi-Fi / companion (MAVLink over UDP) | UDP listen `0.0.0.0:14550` |
| USB telemetry radio (SiK/RFD) | Serial `/dev/ttyUSB0` @ 57600 |
| Flight controller on USB | Serial `/dev/ttyACM0` @ 115200 |
| FC / radio on Pi GPIO UART | Serial `/dev/serial0` @ 57600 (match the FC) |

**Auto** (the default) tries every USB serial device and `/dev/serial0` at
57600 and 115200, then listens for UDP on `0.0.0.0:14550` — each try waits
10 s, so give it up to a minute, or pick the exact link above to connect
immediately.

3. Power the drone — the status should flip to **CONNECTED** with live
   telemetry (battery, GPS, mode). If it stays DISCONNECTED, the Connection
   dialog (click the status pill, top right) shows the exact error.

### Not connecting? (most common first)

| Connection dialog says | Fix |
|------|-----|
| *Permission denied on /dev/…* | Not in `dialout`, or not rebooted since adding it — see above. |
| *No vehicle heartbeat on /dev/…* | Wrong baud (radio 57600 / USB 115200), TX/RX swapped, or the FC port is not set to MAVLink. On the GPIO UART also check the serial console is off. |
| *… is in use by another program* | Close QGroundControl / MAVProxy. `sudo apt remove brltty modemmanager` if they grab USB radios. |
| *UDP port already in use* | Another GCS is listening on 14550 — close it. |
| Waiting on UDP forever | The drone must send to **this Pi's IP**, port 14550; check `sudo ufw status` / firewall. |

Run `ls -l /dev/serial0 /dev/ttyUSB* /dev/ttyACM*` to see which devices exist.

**Dry run without a drone:** `./main.py --sim` starts a simulated vehicle
demo (clearly marked simulated — it can never be mistaken for a live link).

---

## Field checklist

- [ ] App launches and HUD renders (video, tapes, compass)
- [ ] DISCONNECTED shown before drone link, CONNECTED after power-up
- [ ] Heartbeat/battery/GPS/mode live values update
- [ ] Arming + mode changes work (PX4 and ArduPilot)
- [ ] Mission upload (if testing mission planner)
- [ ] `--sim` demo works for offline demonstration

Report issues with: platform (laptop/Pi + distro version), link type
(UDP/serial), and a screenshot of the HUD.
