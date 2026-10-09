# Ghost Controller — Field Test Install Guide

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

**Updates:** the AppImage embeds an update feed pointing at this same GitHub
release. When a new release is published, the running app (or any
AppImageUpdate-capable tool) picks it up automatically — no re-download needed.

**Not on your distro's list?** Any x86_64 Linux with glibc works (Ubuntu
20.04+, Debian 11+, Fedora, Arch…). Testers on Windows/macOS: use a laptop
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

USB telemetry radios and UARTs need group `dialout`:

```bash
sudo usermod -aG dialout $USER   # log out and back in after
```

---

## C. Connecting to the drone (both platforms)

1. Launch Ghost Controller — it starts **DISCONNECTED** (never fakes a link).
2. The HUD shows the configured listening address. Common setups:

| Link | Setting |
|------|---------|
| Wi-Fi / companion (MAVLink over UDP) | UDP listen `0.0.0.0:14550` |
| USB telemetry radio | Serial `/dev/ttyUSB0` (or `ttyACM0`) @ 57600 |
| RPi SiK/UART radio | Serial `/dev/ttyAMA0` @ 57600 |

3. Power the drone — the status should flip to **CONNECTED** with live
   telemetry (battery, GPS, mode). If it stays DISCONNECTED, the HUD will
   show the address it is listening on — check firewall/port and radio wiring.

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
