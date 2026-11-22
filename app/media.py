"""Mediabibliotheek: bestanden in de mediamap, met duur, resolutie en miniaturen."""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import unicodedata

from .store import atomic_write_json

log = logging.getLogger("kiosk.media")

VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".mpg", ".mpeg", ".ts", ".wmv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}
ALLOWED_EXT = VIDEO_EXT | IMAGE_EXT


def kind_of(name: str) -> str | None:
    ext = os.path.splitext(name)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    return None


def clean_filename(name: str) -> str:
    """Maak een veilige bestandsnaam, maar behoud spaties en accenten."""
    name = unicodedata.normalize("NFC", os.path.basename(name.replace("\\", "/")))
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w\s\-().,&+]", "_", stem, flags=re.UNICODE)
    stem = re.sub(r"\s+", " ", stem).strip(" ._") or "bestand"
    return stem[:150] + ext.lower()


class MediaLibrary:
    def __init__(self, media_dir: str, thumb_dir: str, meta_path: str):
        self.media_dir = media_dir
        self.thumb_dir = thumb_dir
        self.meta_path = meta_path
        self.lock = threading.RLock()
        self.meta: dict = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    self.meta = json.load(f)
            except (OSError, ValueError):
                self.meta = {}
        self.ffprobe = shutil.which("ffprobe")
        self.ffmpeg = shutil.which("ffmpeg")
        self._jobs: queue.Queue = queue.Queue()
        self._pending: set = set()
        threading.Thread(target=self._worker, name="media-probe", daemon=True).start()

    # --- paden ------------------------------------------------------------
    def path_for(self, name: str) -> str | None:
        """Volledig pad voor een bestandsnaam uit de bibliotheek, of None."""
        if not name or name != os.path.basename(name) or name.startswith("."):
            return None
        if kind_of(name) is None:
            return None
        path = os.path.join(self.media_dir, name)
        return path if os.path.isfile(path) else None

    def thumb_path(self, name: str) -> str:
        return os.path.join(self.thumb_dir, name + ".jpg")

    def unique_name(self, wanted: str) -> str:
        name = clean_filename(wanted)
        stem, ext = os.path.splitext(name)
        candidate, n = name, 1
        while os.path.exists(os.path.join(self.media_dir, candidate)):
            n += 1
            candidate = f"{stem} ({n}){ext}"
        return candidate

    # --- overzicht ----------------------------------------------------------
    def list(self) -> list:
        items = []
        try:
            entries = list(os.scandir(self.media_dir))
        except FileNotFoundError:
            entries = []
        names = set()
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_file():
                continue
            kind = kind_of(entry.name)
            if not kind:
                continue
            names.add(entry.name)
            st = entry.stat()
            with self.lock:
                meta = self.meta.get(entry.name)
                stale = not meta or meta.get("size") != st.st_size or meta.get("mtime") != int(st.st_mtime)
            if stale:
                self.enqueue(entry.name)
                meta = {}
            items.append({
                "name": entry.name,
                "kind": kind,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "duration": meta.get("duration"),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "thumb": bool(meta.get("thumb")),
                "probing": stale,
            })
        with self.lock:
            gone = [n for n in self.meta if n not in names]
            for n in gone:
                self.meta.pop(n, None)
            if gone:
                self._save_meta()
        items.sort(key=lambda m: m["mtime"], reverse=True)
        return items

    def info(self, name: str) -> dict:
        with self.lock:
            return dict(self.meta.get(name) or {})

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        if not path:
            return False
        os.unlink(path)
        try:
            os.unlink(self.thumb_path(name))
        except FileNotFoundError:
            pass
        with self.lock:
            self.meta.pop(name, None)
            self._save_meta()
        return True

    def disk(self) -> dict:
        usage = shutil.disk_usage(self.media_dir)
        return {"total": usage.total, "free": usage.free, "used": usage.used}

    # --- achtergrondwerk -------------------------------------------------
    def enqueue(self, name: str) -> None:
        with self.lock:
            if name in self._pending:
                return
            self._pending.add(name)
        self._jobs.put(name)

    def _save_meta(self) -> None:
        atomic_write_json(self.meta_path, self.meta)

    def _worker(self) -> None:
        while True:
            name = self._jobs.get()
            try:
                self._probe(name)
            except Exception:  # pragma: no cover - mag de worker nooit stoppen
                log.exception("Analyse van %s mislukt", name)
            finally:
                with self.lock:
                    self._pending.discard(name)

    def _probe(self, name: str) -> None:
        path = self.path_for(name)
        if not path:
            return
        st = os.stat(path)
        meta = {"size": st.st_size, "mtime": int(st.st_mtime), "duration": None,
                "width": None, "height": None, "thumb": False}
        kind = kind_of(name)
        if self.ffprobe:
            try:
                out = subprocess.run(
                    [self.ffprobe, "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height:format=duration",
                     "-of", "json", path],
                    capture_output=True, text=True, timeout=60)
                data = json.loads(out.stdout or "{}")
                stream = (data.get("streams") or [{}])[0]
                meta["width"] = stream.get("width")
                meta["height"] = stream.get("height")
                if kind == "video":
                    dur = (data.get("format") or {}).get("duration")
                    meta["duration"] = round(float(dur), 2) if dur not in (None, "N/A") else None
            except (subprocess.SubprocessError, ValueError, OSError) as exc:
                log.warning("ffprobe faalde voor %s: %s", name, exc)
        if self.ffmpeg:
            os.makedirs(self.thumb_dir, exist_ok=True)
            thumb = self.thumb_path(name)
            tmp = thumb + ".tmp.jpg"
            seeks = ["3", "0"] if kind == "video" else [None]
            for seek in seeks:
                cmd = [self.ffmpeg, "-v", "error", "-y"]
                if seek and (meta["duration"] or 0) > float(seek):
                    cmd += ["-ss", seek]
                cmd += ["-i", path, "-frames:v", "1",
                        "-vf", "scale=480:-2:force_original_aspect_ratio=decrease",
                        "-q:v", "4", tmp]
                try:
                    subprocess.run(cmd, capture_output=True, timeout=60)
                except (subprocess.SubprocessError, OSError):
                    continue
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    os.replace(tmp, thumb)
                    meta["thumb"] = True
                    break
        with self.lock:
            self.meta[name] = meta
            self._save_meta()
