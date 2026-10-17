# Updating Ghost Controller

Your settings (connection, battery profile, video source, appearance) are
kept across updates. Close the app before updating.

## Check which version you have

Open the **Ghost Controller ▾** menu (top-left). The version is shown at the
bottom of the menu, for example `v0.2.1`. The newest release is always at
<https://github.com/Sai-Tolle/Ghost-Controller-/releases/latest>.

---

## Laptop / desktop PC (x86_64 AppImage)

### Option A — re-run the installer (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
```

It downloads the latest release, **verifies its SHA-256 checksum**, and only
then replaces the old AppImage. If the download is interrupted or corrupt,
your current version keeps working.

### Option B — delta update with AppImageUpdate

The AppImage carries its own update feed, so only the changed blocks are
downloaded:

```bash
appimageupdatetool ~/Applications/Ghost_Controller-x86_64.AppImage
```

(Get `appimageupdatetool` from
<https://github.com/AppImageCommunity/AppImageUpdate/releases>. GNOME Software
and AppImageLauncher can use the same feed.)

### Option C — manual download

1. Download `Ghost_Controller-x86_64.AppImage` and its `.sha256` file from the
   latest release.
2. Check it: `sha256sum -c Ghost_Controller-x86_64.AppImage.sha256`
3. Replace `~/Applications/Ghost_Controller-x86_64.AppImage` with it and make
   it executable: `chmod +x ~/Applications/Ghost_Controller-x86_64.AppImage`

---

## Raspberry Pi (runs from source)

Re-run the same installer — on a Pi it updates the existing checkout
(`git pull`), installs any new dependencies and keeps `backend/gcs.env`:

```bash
curl -fsSL https://raw.githubusercontent.com/Sai-Tolle/Ghost-Controller-/main/install.sh | bash
```

Or update by hand (system Qt/numpy/PyAV/OpenCV come from apt, so they are
skipped here):

```bash
cd ~/Ghost-Controller- && git pull --ff-only && grep -vE '^(PySide6|numpy|av==|opencv)' requirements.txt | .venv/bin/pip install -q -r /dev/stdin
```

If `git pull` refuses because files were edited locally, run
`git -C ~/Ghost-Controller- status` and send us the output.

---

## Verify the update worked

1. Menu shows the new version number (bottom of the Ghost Controller ▾ menu).
2. Laptop only — the file matches the release checksum:

   ```bash
   cd ~/Applications && curl -fsSL -O https://github.com/Sai-Tolle/Ghost-Controller-/releases/latest/download/Ghost_Controller-x86_64.AppImage.sha256 && sha256sum -c Ghost_Controller-x86_64.AppImage.sha256
   ```

   It must print `Ghost_Controller-x86_64.AppImage: OK`.
3. Quick self-test without opening a window:

   ```bash
   ~/Applications/Ghost_Controller-x86_64.AppImage --smoke
   ```

   (Pi: `~/Ghost-Controller-/launch-ghost.sh --smoke`) — it must print
   `SMOKE_OK`.

## Something went wrong?

- **Desktop icon still opens the old version** — an older copy may exist
  (e.g. `~/Applications/GhostHandler.AppImage` from before the rename). The
  icon runs `~/Applications/Ghost_Controller-x86_64.AppImage`; delete the old
  file.
- **"CHECKSUM MISMATCH"** — the download was damaged; run the installer
  again. Nothing was changed.
- **App closes by itself** — update to v0.2.2 or newer (v0.2.0/v0.2.1 had a
  crash about a minute after launch). If it still happens, send
  `~/.cache/ghost-controller/crash.log`.
- **Pi: app does not start after updating** — re-run the installer; it
  reinstalls missing system packages.
