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
    curl -fL -o "$HOME/.local/share/icons/hicolor/256x256/apps/ghost-handler.png" \
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
    say "Installed. Start it from the app menu, or run:"
    echo "    $DEST/Ghost_Controller-x86_64.AppImage"
    ;;

aarch64)
    say "Raspberry Pi detected — installing system packages (Qt has no ARM64 pip wheels)..."
    sudo apt-get update
    sudo apt-get install -y git python3 python3-pip python3-venv \
        python3-pyside6.qtquick python3-pyside6.qtwidgets \
        python3-numpy python3-av python3-opencv \
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

    say "Serial telemetry radios need the dialout group (log out/in after):"
    echo "    sudo usermod -aG dialout \$USER"
    say "Installed. Start the app with:"
    echo "    $HOME/Ghost-Controller-/.venv/bin/python $HOME/Ghost-Controller-/main.py"
    ;;

*)
    echo "Unsupported architecture: $ARCH (need x86_64 or aarch64)" >&2
    exit 1
    ;;
esac
