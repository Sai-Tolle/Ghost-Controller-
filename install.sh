#!/usr/bin/env bash
# Ghost Controller — one-line installer for field testers.
#
#   curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
#
# x86_64 : downloads the AppImage from the latest GitHub release (auto-updating
#          via the embedded AppImageUpdate feed) and adds a menu entry.
# aarch64: Raspberry Pi — installs apt deps (Qt has no ARM64 pip wheels), clones
#          the repo and sets up a venv; you run the app from source.
#          See docs/TESTERS.md for details.
set -euo pipefail

REPO="Sai-Tolle/Ghost-Controller-"
ARCH=$(uname -m)
RELEASE_BASE="https://github.com/$REPO/releases/latest/download"

say() { printf '\n>> %s\n' "$*"; }

case "$ARCH" in
x86_64)
    DEST="$HOME/Applications"
    mkdir -p "$DEST"
    say "Downloading Ghost_Controller-x86_64.AppImage from the latest release..."
    curl -fL --progress-bar -o "$DEST/Ghost_Controller-x86_64.AppImage" \
        "$RELEASE_BASE/Ghost_Controller-x86_64.AppImage"
    curl -fL -o "$DEST/Ghost_Controller-x86_64.AppImage.zsync" \
        "$RELEASE_BASE/Ghost_Controller-x86_64.AppImage.zsync" || true
    chmod +x "$DEST/Ghost_Controller-x86_64.AppImage"

    say "Installing app menu entry + icon..."
    mkdir -p "$HOME/.local/share/applications" \
             "$HOME/.local/share/icons/hicolor/256x256/apps"
    ICON="$HOME/.local/share/icons/hicolor/256x256/apps/ghost-handler.png"
    curl -fL -o "$ICON" \
        "https://raw.githubusercontent.com/$REPO/main/design/icon-256.png" || true
    cat > "$HOME/.local/share/applications/ghost-handler.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec=$DEST/Ghost_Controller-x86_64.AppImage
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
Exec=$DEST/Ghost_Controller-x86_64.AppImage
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

    if [ ! -d "$HOME/Ghost-Controller-" ]; then
        say "Cloning source..."
        git clone "https://github.com/$REPO.git" "$HOME/Ghost-Controller-"
    fi
    cd "$HOME/Ghost-Controller-"

    if [ ! -x .venv/bin/python ]; then
        say "Setting up venv (system PySide6 + pip remainder)..."
        python3 -m venv --system-site-packages .venv
        grep -vE '^(PySide6|numpy|av==|opencv)' requirements.txt \
            | .venv/bin/pip install -r /dev/stdin
    fi

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
    curl -fL -o "$ICON" \
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
Exec=$HOME/Ghost-Controller-/launch-ghost.sh
Icon=$ICON
Categories=Utility;
Terminal=false
EOF
    chmod +x "$DESKTOP_DIR/ghost-controller.desktop"
    if command -v gio >/dev/null 2>&1; then
        gio set "$DESKTOP_DIR/ghost-controller.desktop" metadata::trusted true 2>/dev/null || true
    fi

    say "Serial telemetry radios need the dialout group (log out/in after):"
    echo "    sudo usermod -aG dialout \$USER"
    say "Installed. Launch it by double-clicking the Ghost Controller icon
       on your Desktop, or from a terminal:"
    echo "    $HOME/Ghost-Controller-/launch-ghost.sh"
    ;;

*)
    echo "Unsupported architecture: $ARCH (need x86_64 or aarch64)" >&2
    exit 1
    ;;
esac
