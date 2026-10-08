"""Online OSM tile fetcher for the desktop map — web parity with Leaflet's
TileLayer (https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png).

Design notes
------------
* urllib stdlib fetch (no requests dependency in the desktop venv).
* Polite default UA (OSM tile policy: a bare UA gets soft-blocked with
  placeholder images). GH_MAP_USER_AGENT overrides.
* Disk cache (~/.cache/ghost-handler/osm-tiles) so a flown area re-renders
  offline afterwards — the operator can pre-fly a region while connected and
  keep maps for the field. Entries never expire (tiles are effectively
  immutable; OSM retires old zooms very slowly).
* Single-flight: concurrent fetches for the same tile coalesce on a lock.
* Hard failure after `retries` attempts → tile reported missing, QML paints
  the offline/grid fallback. The app NEVER blocks the GUI thread waiting on
  the network — fetches happen inside QML-delegated provider calls, which
  Qt runs on the GUI thread, so timeouts stay small (1.5 s) and every miss
  is cached-negative briefly to avoid hammering a dead network.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import ssl
import threading
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
import time
import urllib.request
from pathlib import Path

# GH_OSM_TILE_URL lets you point at a self-hosted / proxy tile server (and lets the tests
# run against a local server). Default is the public OSM server.
OSM_TILE_URL = os.environ.get("GH_OSM_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
DEFAULT_UA = "GhostHandlerDesktop/1.0 (ground control station; contact: operator@local)"
NEGATIVE_TTL = 30.0  # seconds a failed tile stays "known missing"

# ONE TLS context for every tile. urlopen() used to build a fresh context per
# tile, and loading the system CA store holds the Python GIL for tens of ms:
# with 8 tile workers that starved the GUI thread (UI stutter while zooming).
_SSL_CTX = ssl.create_default_context()


def write_atomic(path: Path, data: bytes) -> bool:
    """Write via temp file + rename: QML loads tiles from disk by URL, so it
    must never see a half-written PNG."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


class OsmTileFetcher:
    """Fetches + caches OSM PNG tiles; `tile(z,x,y) -> bytes | None`."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        cache_root = os.environ.get("GH_OSM_CACHE")
        if cache_root:
            root = Path(cache_root)
        else:
            base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
            root = Path(base) / "ghost-handler" / "osm-tiles"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # QML now loads tiles straight from this folder, so it must exist.
            import tempfile
            root = Path(tempfile.gettempdir()) / "ghost-handler-osm-tiles"
            root.mkdir(parents=True, exist_ok=True)
        self._cache_dir = root
        self._neg: dict[tuple[int, int, int], float] = {}
        self._mem: dict[tuple[int, int, int], bytes] = {}
        self._mem_order: list[tuple[int, int, int]] = []
        self._mem_limit = 768            # ~256x256 PNGs, tens of MB at most
        # Tiles used to be fetched one at a time inside Qt's single image-reader
        # thread, so a zoom loaded tiles strictly serially. A small pool fetches
        # the whole viewport in parallel; the provider just waits on the future.
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="osm-tile")
        self._inflight: dict[tuple[int, int, int], Future] = {}
        # Low-priority queue (next/previous zoom warm-up). Fed to the pool only
        # while it has idle workers, so tiles that are ON SCREEN never wait
        # behind speculative ones.
        self._low: list[tuple[int, int, int]] = []
        self._workers = 8
        # Keep-alive: each worker reuses its own HTTPS connection instead of a
        # new TCP + TLS handshake per tile. Falls back to urllib (which honours
        # HTTP(S)_PROXY) when a proxy applies to the tile host.
        self._local = threading.local()
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX))
        self._fail_streak = 0
        self._ready_cb = None            # called (from a worker thread) when a tile finishes downloading
        self._lock = threading.Lock()
        self._ua = os.environ.get("GH_MAP_USER_AGENT", DEFAULT_UA)
        self._online = True  # flipped off after repeated hard failures

    # ---- properties ----

    @property
    def online(self) -> bool:
        """False once fetches stopped succeeding (network down / blocked)."""
        return self._online

    # ---- public ----

    def _mem_get(self, key):
        with self._lock:
            if key in self._mem:
                try:
                    self._mem_order.remove(key)
                except ValueError:
                    pass
                self._mem_order.append(key)
                return self._mem[key]
        return None

    def _mem_put(self, key, data: bytes) -> None:
        with self._lock:
            self._mem[key] = data
            try:
                self._mem_order.remove(key)
            except ValueError:
                pass
            self._mem_order.append(key)
            while len(self._mem_order) > self._mem_limit:
                self._mem.pop(self._mem_order.pop(0), None)

    def peek(self, z: int, x: int, y: int) -> bytes | None:
        """Cache-only lookup (memory, then disk). NEVER touches the network —
        used for the instant low-resolution placeholders shown while sharp tiles load."""
        key = (z, x, y)
        data = self._mem_get(key)
        if data is not None:
            return data
        path = self._cache_path(key)
        try:
            if path.exists() and path.stat().st_size > 0:
                data = path.read_bytes()
                self._mem_put(key, data)
                return data
        except OSError:
            pass
        return None

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def cached_path(self, z: int, x: int, y: int) -> Path | None:
        """Disk path of a downloaded tile, or None. Cheap (one stat)."""
        path = self._cache_path((z, x, y))
        try:
            return path if path.stat().st_size > 0 else None
        except OSError:
            return None

    def submit_job(self, fn, *args):
        """Run `fn(*args)` on the tile pool (used for offline-source tiles)."""
        return self._pool.submit(fn, *args)

    def set_ready_callback(self, cb) -> None:
        self._ready_cb = cb

    def schedule(self, z: int, x: int, y: int) -> None:
        """Start a background fetch for one tile without waiting (no-op if cached,
        in flight or recently failed)."""
        self.prefetch([(z, x, y)])

    def _job(self, key):
        data = self._fetch(key)
        if data is not None:
            self._mem_put(key, data)
            cb = self._ready_cb
            if cb is not None:
                try:
                    cb(key)
                except Exception:  # noqa: BLE001
                    pass
        else:
            with self._lock:
                self._neg[key] = time.monotonic()
        return data

    def _submit(self, key) -> Future:
        with self._lock:
            fut = self._inflight.get(key)
            if fut is not None:
                return fut
            fut = self._pool.submit(self._job, key)
            self._inflight[key] = fut
        fut.add_done_callback(lambda _f, k=key: (self._inflight.pop(k, None), self._pump()))
        return fut

    def _pump(self) -> None:
        while True:
            with self._lock:
                if not self._low or len(self._inflight) >= self._workers:
                    return
                key = self._low.pop(0)
                if key in self._mem or key in self._inflight:
                    continue
            if self.peek(*key) is None:
                self._submit(key)

    def prefetch_low(self, keys, replace: bool = False) -> None:
        """Queue speculative tiles; `replace` drops the previous speculation
        (the user zoomed again, the old neighbours are no longer likely)."""
        now = time.monotonic()
        with self._lock:
            if replace:
                self._low.clear()
            have = set(self._low)
            for key in keys:
                if key in have or key in self._mem or key in self._inflight:
                    continue
                neg_ts = self._neg.get(key)
                if neg_ts is not None and (now - neg_ts) < NEGATIVE_TTL:
                    continue
                self._low.append(key)
                have.add(key)
            del self._low[300:]
        self._pump()

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        """Tile bytes, fetching in the pool if needed (waits for the result)."""
        key = (z, x, y)
        data = self.peek(z, x, y)
        if data is not None:
            return data
        with self._lock:
            neg_ts = self._neg.get(key)
            if neg_ts is not None and (time.monotonic() - neg_ts) < NEGATIVE_TTL:
                return None
        try:
            return self._submit(key).result(timeout=8.0)
        except Exception:  # noqa: BLE001 — timeout / worker error -> treat as missing
            return None

    def prefetch(self, keys) -> int:
        """Start fetching tiles in the background (non-blocking). Returns how many
        were queued. Skips cached, known-missing and already in-flight tiles and caps
        the queue so a fast pan can't flood the server."""
        queued = 0
        now = time.monotonic()
        for key in keys:
            with self._lock:
                if key in self._mem or key in self._inflight:
                    continue
                neg_ts = self._neg.get(key)
                if neg_ts is not None and (now - neg_ts) < NEGATIVE_TTL:
                    continue
                if len(self._inflight) >= 96:
                    break
            if self.peek(*key) is not None:
                continue
            self._submit(key)
            queued += 1
        return queued

    def clear_negative(self) -> None:
        with self._lock:
            self._neg.clear()
        self._online = True

    # ---- internals ----

    def _get(self, url: str, fresh: bool) -> bytes:
        """GET over a per-thread persistent connection (proxy-aware fallback)."""
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ""
        proxies = urllib.request.getproxies()
        if proxies.get(u.scheme) and not urllib.request.proxy_bypass(host):
            req = urllib.request.Request(url, headers={"User-Agent": self._ua,
                                                       "Accept": "image/png,image/*;q=0.8"})
            with self._opener.open(req, timeout=2.5) as resp:
                return resp.read()
        key = (u.scheme, host, u.port)
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        conn = None if fresh else conns.get(key)
        if conn is None:
            if u.scheme == "https":
                conn = http.client.HTTPSConnection(host, u.port or 443, timeout=2.5, context=_SSL_CTX)
            else:
                conn = http.client.HTTPConnection(host, u.port or 80, timeout=2.5)
            conns[key] = conn
        path = u.path + ("?" + u.query if u.query else "")
        try:
            conn.request("GET", path, headers={"User-Agent": self._ua, "Accept": "image/png,image/*;q=0.8",
                                               "Connection": "keep-alive"})
            resp = conn.getresponse()
            data = resp.read()
        except Exception:
            conn.close()
            conns.pop(key, None)
            raise
        if resp.status != 200:
            raise OSError(f"HTTP {resp.status}")
        if resp.getheader("Connection", "").lower() == "close":
            conn.close()
            conns.pop(key, None)
        return data

    def _cache_path(self, key: tuple[int, int, int]) -> Path:
        digest = hashlib.sha1(f"{key[0]}/{key[1]}/{key[2]}".encode()).hexdigest()[:2]
        return self._cache_dir / digest / f"{key[0]}-{key[1]}-{key[2]}.png"

    def _fetch(self, key: tuple[int, int, int]) -> bytes | None:
        path = self._cache_path(key)
        if path.exists() and path.stat().st_size > 0:
            try:
                return path.read_bytes()
            except OSError:
                pass
        url = OSM_TILE_URL.format(z=key[0], x=key[1], y=key[2])
        for attempt in range(2):
            try:
                data = self._get(url, attempt > 0)
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    self._online = True
                    self._fail_streak = 0
                    write_atomic(path, data)
                    return data
                # OSM soft-block placeholder: not a real PNG payload
                return None
            except Exception:  # noqa: BLE001 — network errors are expected
                self._fail_streak += 1
                if self._fail_streak >= 3:       # one slow tile is not "offline"
                    self._online = False
                if attempt == 0:
                    time.sleep(0.3)
        return None
