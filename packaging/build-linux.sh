#!/usr/bin/env bash
# Build Ghost Handler Desktop for Linux (primary target).
#   ./packaging/build-linux.sh            -> dist/ghost-handler/ (onedir bundle)
#   ./packaging/build-linux.sh --appimage -> additionally builds a .AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=${VENV:-.venv-desktop}
PY="$VENV/bin/python"

# Target architecture: PyInstaller cannot cross-compile, so this script must
# run ON the architecture it builds for (x86_64 laptop, aarch64 Pi/CI runner).
ARCH=$(uname -m)

# AppImageUpdate feed settings (embedded as update-information in the AppImage):
#   GH_REPO   e.g. "yourname/GCS-Desktop"  -> gh-releases-zsync feed on GitHub Releases
#   APP_VER   read from pyproject.toml (tomllib on 3.11+, regex fallback on 3.10)
GH_REPO=${GH_REPO:-${GITHUB_REPOSITORY:-}}
# sed (not tomllib) so this works on Python 3.10 too; captures e.g. version = "0.1.0"
APP_VER=$(sed -n "s/^version[[:space:]]*=[[:space:]]*\"\([0-9][0-9.]*\)\"/\1/p" pyproject.toml | head -n1)

if [ ! -x "$PY" ]; then
    if [ "$ARCH" = "aarch64" ]; then
        # ARM64: PyPI has NO aarch64 wheels for PySide6/numpy/PyAV/OpenCV.
        # Those come from apt (Debian trixie: python3-pyside6.qtquick etc.);
        # the venv needs system site-packages and pip installs only the
        # pure-Python remainder of requirements.txt.
        python3 -m venv --system-site-packages "$VENV"
        "$VENV/bin/pip" install --upgrade pip
        grep -vE '^(PySide6|numpy|av==|opencv)' requirements.txt | "$VENV/bin/pip" install -r /dev/stdin
        "$VENV/bin/pip" install pyinstaller
    else
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install --upgrade pip
        "$VENV/bin/pip" install -r requirements.txt
        "$VENV/bin/pip" install pyinstaller
    fi
fi

echo "== regenerate tokens =="
"$PY" tools/gen_tokens.py

echo "== smoke test (headless) =="
"$PY" tests/smoke_test.py

echo "== pyinstaller =="
"$VENV/bin/pyinstaller" --noconfirm --clean packaging/ghost-handler.spec
echo "bundle: dist/ghost-handler/ghost-handler"

if [ "${1:-}" = "--appimage" ]; then
    echo "== AppImage =="
    # linuxdeploy publishes per-arch binaries; pick ours (x86_64 / aarch64).
    LD_NAME="linuxdeploy-${ARCH}.AppImage"
    if ! command -v "$LD_NAME" >/dev/null 2>&1; then
        if [ ! -x "/tmp/$LD_NAME" ]; then
            echo "linuxdeploy not found; fetching $LD_NAME..."
            curl -L -o "/tmp/$LD_NAME" \
                "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/$LD_NAME"
            chmod +x "/tmp/$LD_NAME"
        fi
        LINUXDEPLOY=/tmp/$LD_NAME
    else
        LINUXDEPLOY=$LD_NAME
    fi
    # Allow running AppImages inside containers/CI where FUSE is unavailable.
    export APPIMAGE_EXTRACT_AND_RUN=1

    APPDIR=$(mktemp -d)/GhostHandler.AppDir
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    cp -r dist/ghost-handler/. "$APPDIR/usr/bin/"
    cp design/icon-256.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/ghost-handler.png" 2>/dev/null || true

    cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/ghost-handler" "$@"
EOF
    chmod +x "$APPDIR/AppRun"

    cat > /tmp/ghost-handler.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Ghost Controller
Comment=UAV Ground Control Station
Exec=ghost-handler
Icon=ghost-handler
Categories=Utility;
X-AppImage-Version=$APP_VER
EOF

    # AppStream metadata so GNOME Software / KDE Discover / distro app centers
    # can list the app (and, with an AppImageUpdate feed, update it). The Freedesktop
    # AppStream standard requires the metainfo file to be named <component-id>.metainfo.xml
    # and placed at usr/share/metainfo/ inside the AppDir; linuxdeploy's appimage plugin
    # (appimagetool) reads it from there. The file is docs/com.yourdomain.GhostController.metainfo.xml.
    if [ -f "$(pwd)/docs/com.yourdomain.GhostController.metainfo.xml" ]; then
        METAINFO_DIR="$APPDIR/usr/share/metainfo"
        mkdir -p "$METAINFO_DIR"
        cp "$(pwd)/docs/com.yourdomain.GhostController.metainfo.xml" "$METAINFO_DIR/com.yourdomain.GhostController.metainfo.xml"
        echo "appdata: bundled docs/com.yourdomain.GhostController.metainfo.xml -> $METAINFO_DIR/"
    fi

    # Embed update-information so AppImageUpdate / GNOME Software can fetch
    # updates. With GH_REPO set (type-2 AppImage), linuxdeploy writes the
    # appimageupdate.yml feed reference into the bundle; X-AppImage-Update-Info
    # is consumed by the updater.
    # Update-information is passed to the bundled appimage output plugin via
    # the LDAI_UPDATE_INFORMATION env var (linuxdeploy core has no CLI flag for
    # it). NOTE: the appimagetool bundled with continuous linuxdeploy only
    # accepts zsync-style update types (gh-releases-zsync, zsync, pling), NOT
    # the plain gh-releases type. So we embed gh-releases-zsync and generate a
    # .zsync sidecar (delta updates) after the AppImage is produced.
    ZSYNCCMAKE=${ZSYNCCMAKE:-zsyncmake}
    # Output name is derived from the desktop file's Name= + target arch
    # (Ghost Controller -> Ghost_Controller-x86_64.AppImage, or _-aarch64).
    # The embedded feed MUST point at the per-arch .zsync filename.
    EXPECTED_NAME="Ghost_Controller-${ARCH}.AppImage"
    UPDATE_ENV=()
    if [ -n "$GH_REPO" ]; then
        UPDATE_ENV=(env "LDAI_UPDATE_INFORMATION=gh-releases-zsync|${GH_REPO%%/*}|${GH_REPO#*/}|latest|${EXPECTED_NAME}.zsync")
    fi
    if [ -f "dist/$EXPECTED_NAME" ]; then
        rm -f "dist/$EXPECTED_NAME"
    fi
    ( cd dist && "${UPDATE_ENV[@]}" "$LINUXDEPLOY" --appdir "$APPDIR" \
        --desktop-file /tmp/ghost-handler.desktop \
        --output appimage )
    if [ -f "dist/$EXPECTED_NAME" ]; then
        chmod +x "dist/$EXPECTED_NAME"
        echo "AppImage: dist/$EXPECTED_NAME"
        # Generate the .zsync sidecar the embedded feed points at. -u is the
        # public URL where the AppImage will live on GitHub Releases; it is
        # written into the .zsync as metadata for the updater.
        if command -v "$ZSYNCCMAKE" >/dev/null 2>&1; then
            ( cd dist && "$ZSYNCCMAKE" -u "https://github.com/${GH_REPO}/releases/latest/download/$EXPECTED_NAME" \
                -o "$EXPECTED_NAME.zsync" "$EXPECTED_NAME" )
            echo "zsync feed: dist/$EXPECTED_NAME.zsync"
        else
            echo "WARNING: zsyncmake not found - AppImage has update info but no .zsync sidecar was generated" >&2
            echo "         (build it: see /tmp/zsync-upstream-0.6.2, or sudo apt install zsync)" >&2
        fi
    else
        echo "ERROR: AppImage not produced in dist/" >&2
        exit 1
    fi
fi
