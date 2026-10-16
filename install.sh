#!/usr/bin/env bash
# Ghost Controller — one-line installer for field testers.
#
#   curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
#
# Run the same command again at any time to UPDATE an existing install.
#
# x86_64 : downloads the AppImage from the latest GitHub release (auto-updating
#          via the embedded AppImageUpdate feed) and adds a menu entry.
# aarch64: Raspberry Pi — installs apt deps (Qt has no ARM64 pip wheels), clones
#          the repo and sets up a venv; you run the app from source.
#          See docs/TESTERS.md for details.
set -euo pipefail
umask 022

# Never run the whole installer as root: it writes into $HOME and would leave
# root-owned files behind. The Pi branch calls sudo itself for apt only.
if [ "$(id -u)" -eq 0 ]; then
    echo "Do not run this installer as root (no sudo). It asks for sudo itself when needed." >&2
    exit 1
fi

REPO="Sai-Tolle/Ghost-Controller-"
ARCH=$(uname -m)
RELEASE_BASE="https://github.com/$REPO/releases/latest/download"

say() { printf '\n>> %s\n' "$*"; }

# HTTPS only, TLS 1.2+, fail on HTTP errors; refuses a redirect to plain http.
fetch() { curl -fL --proto '=https' --tlsv1.2 "$@"; }

# Everything in the wrapper function runs only after the whole script has been
# downloaded, so a connection that drops mid-`curl | bash` cannot execute half
# an installer.
main() {

case "$ARCH" in
x86_64)
    DEST="$HOME/Applications"
    APP="Ghost_Controller-x86_64.AppImage"
    mkdir -p "$DEST"
    # Download next to the target, verify, then rename into place: an
    # interrupted or tampered download never replaces a working install and is
    # never made executable.
    TMP=$(mktemp -d "$DEST/.ghost-install.XXXXXX")
    trap 'rm -rf "$TMP"' EXIT
    say "Downloading $APP from the latest release..."
    fetch --progress-bar -o "$TMP/$APP" "$RELEASE_BASE/$APP"
    say "Verifying SHA-256 checksum..."
    if fetch -sS -o "$TMP/$APP.sha256" "$RELEASE_BASE/$APP.sha256"; then
        ( cd "$TMP" && sha256sum -c "$APP.sha256" ) || {
            echo "CHECKSUM MISMATCH - the download is corrupt or was tampered with. Nothing was installed." >&2
            exit 1
        }
    elif [ "${GHOST_ALLOW_UNVERIFIED:-0}" = "1" ]; then
        echo "WARNING: this release has no checksum file; installing unverified (GHOST_ALLOW_UNVERIFIED=1)." >&2
    else
        echo "This release publishes no .sha256 file, so the download cannot be verified." >&2
        echo "Re-run with GHOST_ALLOW_UNVERIFIED=1 to install anyway." >&2
        exit 1
    fi
    chmod 755 "$TMP/$APP"
    mv -f "$TMP/$APP" "$DEST/$APP"
    fetch -sS -o "$DEST/$APP.zsync" "$RELEASE_BASE/$APP.zsync" || true

    say "Installing app menu entry + icon..."
    mkdir -p "$HOME/.local/share/applications" \
             "$HOME/.local/share/icons/hicolor/256x256/apps"
    ICON="$HOME/.local/share/icons/hicolor/256x256/apps/ghost-handler.png"
    fetch -sS -o "$ICON" \
        "https://raw.githubusercontent.com/$REPO/main/design/icon-256.png" || true
    cat > "$HOME/.local/share/applications/ghost-handler.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec="$DEST/Ghost_Controller-x86_64.AppImage"
Icon=ghost-handler
Categories=Utility;
Terminal=false
EOF

    say "Adding a Ghost Controller icon to your Desktop..."
    DESKTOP_DIR="$HOME/Desktop"
    if command -v xdg-user-dir >/dev/null 2>&1; then
        DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
    fi
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/ghost-controller.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec="$DEST/Ghost_Controller-x86_64.AppImage"
Icon=$ICON
Categories=Utility;
Terminal=false
EOF
    chmod +x "$DESKTOP_DIR/ghost-controller.desktop"
    # GNOME/Ubuntu need the "trusted" metadata bit or the icon shows a
    # generic file + "Allow Launching" prompt.
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/ghost-controller.desktop" metadata::trusted true 2>/dev/null || true
    fi
    say "Installed. Double-click the Ghost Controller icon on your Desktop,
       start it from the app menu, or run:"
    echo "    $DEST/Ghost_Controller-x86_64.AppImage"
    ;;

aarch64)
    say "Raspberry Pi detected — installing system packages (Qt has no ARM64 pip wheels)..."
    sudo apt-get update
    # python3-pyside6.qtquick ships the QtQuick bindings but NOT the QML
    # modules the app imports (QtQuick.Controls/Layouts/Dialogs) — Debian
    # splits each into its own qml6-module-* package, so install them here.
    # Without these the app aborts on launch with "QtQuick.Controls is not
    # installed".
    sudo apt-get install -y git python3 python3-pip python3-venv \
        python3-pyside6.qtquick python3-pyside6.qtwidgets \
        python3-numpy python3-av python3-opencv \
        qml6-module-qtquick qml6-module-qtquick-controls \
        qml6-module-qtquick-layouts qml6-module-qtquick-dialogs \
        qml6-module-qtquick-templates qml6-module-qtquick-shapes \
        qml6-module-qtquick-window qml6-module-qtqml-workerscript \
        libgl1 libegl1

    if [ ! -d "$HOME/Ghost-Controller-/.git" ]; then
        say "Cloning source..."
        git clone "https://github.com/$REPO.git" "$HOME/Ghost-Controller-"
        cd "$HOME/Ghost-Controller-"
    else
        say "Existing install found - updating..."
        cd "$HOME/Ghost-Controller-"
        # backend/gcs.env is local configuration. Older versions tracked it in
        # git; keep the operator's copy across the update either way.
        if [ -f backend/gcs.env ]; then
            cp -p backend/gcs.env "$HOME/.ghost-gcs.env.keep"
            git checkout -- backend/gcs.env 2>/dev/null || true
        fi
        git pull --ff-only
        if [ -f "$HOME/.ghost-gcs.env.keep" ]; then
            mv -f "$HOME/.ghost-gcs.env.keep" backend/gcs.env
            chmod 600 backend/gcs.env
        fi
    fi

    if [ ! -x .venv/bin/python ]; then
        say "Setting up venv (system PySide6 + pip remainder)..."
        python3 -m venv --system-site-packages .venv
    fi
    # Re-run on every install/update so new dependencies are picked up.
    grep -vE '^(PySide6|numpy|av==|opencv)' requirements.txt \
        | .venv/bin/pip install -r /dev/stdin

    say "Creating launcher + Desktop icon..."
    # Launcher script so the app always runs from the repo root regardless of
    # the caller's cwd (the desktop entry execs this directly).
    cat > "$HOME/Ghost-Controller-/launch-ghost.sh" <<'EOF'
#!/bin/sh
cd "$HOME/Ghost-Controller-" || exit 1
exec .venv/bin/python main.py "$@"
EOF
    chmod +x "$HOME/Ghost-Controller-/launch-ghost.sh"

    ICON="$HOME/.local/share/icons/hicolor/256x256/apps/ghost-handler.png"
    mkdir -p "$HOME/.local/share/icons/hicolor/256x256/apps"
    fetch -sS -o "$ICON" \
        "https://raw.githubusercontent.com/$REPO/main/design/icon-256.png" || true

    DESKTOP_DIR="$HOME/Desktop"
    if command -v xdg-user-dir >/dev/null 2>&1; then
        DESKTOP_DIR=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
    fi
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/ghost-controller.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec="$HOME/Ghost-Controller-/launch-ghost.sh"
Icon=$ICON
Categories=Utility;
Terminal=false
EOF
    chmod +x "$DESKTOP_DIR/ghost-controller.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/ghost-controller.desktop" metadata::trusted true 2>/dev/null || true
    fi

    # Print the command with the real username already filled in: testers
    # copied "$USER" literally into other tools / typed "$USER$", and the Pi
    # never got serial access.
    ME=$(id -un)
    if id -nG "$ME" 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
        say "Serial access: $ME is already in the dialout group."
    else
        say "Serial telemetry radios need the dialout group. Run this, then REBOOT:"
        echo "    sudo usermod -aG dialout $ME"
    fi
    say "Installed. Launch it by double-clicking the Ghost Controller icon
       on your Desktop, or from a terminal:"
    echo "    $HOME/Ghost-Controller-/launch-ghost.sh"
    ;;

*)
    echo "Unsupported architecture: $ARCH (need x86_64 or aarch64)" >&2
    exit 1
    ;;
esac
}

main "$@"
