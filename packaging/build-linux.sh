#!/usr/bin/env bash
# Build Ghost Handler Desktop for Linux (primary target).
#   ./packaging/build-linux.sh            -> dist/ghost-handler/ (onedir bundle)
#   ./packaging/build-linux.sh --appimage -> additionally builds a .AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=${VENV:-.venv-desktop}
PY="$VENV/bin/python"

# AppImageUpdate feed settings (embedded as update-information in the AppImage):
#   GH_REPO   e.g. "yourname/GCS-Desktop"  -> gh-releases-zsync feed on GitHub Releases
#   APP_VER   read from pyproject.toml (tomllib on 3.11+, regex fallback on 3.10)
GH_REPO=${GH_REPO:-${GITHUB_REPOSITORY:-}}
# sed (not tomllib) so this works on Python 3.10 too; captures e.g. version = "0.1.0"
APP_VER=$(sed -n "s/^version[[:space:]]*=[[:space:]]*\"\([0-9][0-9.]*\)\"/\1/p" pyproject.toml | head -n1)

if [ ! -x "$PY" ]; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip
    "$VENV/bin/pip" install -r requirements.txt
    "$VENV/bin/pip" install pyinstaller
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
    if ! command -v linuxdeploy-x86_64.AppImage >/dev/null 2>&1; then
        if [ ! -x /tmp/linuxdeploy-x86_64.AppImage ]; then
            echo "linuxdeploy not found; fetching..."
            curl -L -o /tmp/linuxdeploy-x86_64.AppImage \
                https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
            chmod +x /tmp/linuxdeploy-x86_64.AppImage
        fi
        LINUXDEPLOY=/tmp/linuxdeploy-x86_64.AppImage
    else
        LINUXDEPLOY=linuxdeploy-x86_64.AppImage
    fi

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
    UPDATE_ENV=()
    if [ -n "$GH_REPO" ]; then
        UPDATE_ENV=(env "LDAI_UPDATE_INFORMATION=gh-releases-zsync|${GH_REPO%%/*}|${GH_REPO#*/}|latest|Ghost_Controller-x86_64.AppImage.zsync")
    fi
    # Output name is derived from the desktop file's Name= (Ghost Controller ->
    # Ghost_Controller-x86_64.AppImage); detect it so the check below matches.
    EXPECTED_NAME="Ghost_Controller-x86_64.AppImage"
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
