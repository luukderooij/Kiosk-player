"""Software-update via GitHub: een branch kiezen, downloaden, controleren, installeren en herstarten.

De programmamap (op de kiosk /opt/kiosk-player) ziet er zo uit:

  app/                 de draaiende versie
  app.prev/            de vorige versie, voor terugzetten
  app.failed/          een versie die na een update niet startte
  .staging/            tijdelijke downloads
  VERSION.json         welke versie er staat (en de vorige)
  update-state.json    'trial' direct na een update; run.py zet terug als die niet start
  run.py               het startpunt; wordt alleen door install.sh bijgewerkt

Alleen app/ wordt vervangen. Herstarten gaat door het proces te beëindigen: systemd
(Restart=always) start Kiosk Player daarna opnieuw.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from .store import atomic_write_json

log = logging.getLogger("kiosk.updater")

GITHUB_API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
MAX_DOWNLOAD = 50 * 1024 ** 2
CACHE_SECONDS = 60
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = ("app/__init__.py", "app/server.py", "app/static/index.html")


class UpdateError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def commit_summary(c: dict) -> dict:
    commit = c.get("commit") or {}
    return {
        "sha": c.get("sha"),
        "message": (commit.get("message") or "").splitlines()[0][:200] if commit.get("message") else "",
        "date": (commit.get("committer") or {}).get("date"),
        "author": (commit.get("author") or {}).get("name"),
        "url": c.get("html_url"),
    }


class Updater:
    def __init__(self, app_dir: str, repo: str, token: str | None = None, restart=None,
                 event=None, require_systemd: bool = True):
        self.app_dir = os.path.abspath(app_dir)
        self.repo = repo or ""
        self.token = token or None
        self.restart_cb = restart or (lambda: None)
        self.event = event or (lambda level, message: None)
        self.require_systemd = require_systemd
        self.lock = threading.Lock()
        self.job: dict = {"status": "idle"}
        self._cache: dict = {}

    # --- paden ----------------------------------------------------------------
    def _p(self, *parts) -> str:
        return os.path.join(self.app_dir, *parts)

    @property
    def current_dir(self) -> str:
        return self._p("app")

    @property
    def prev_dir(self) -> str:
        return self._p("app.prev")

    @property
    def staging_dir(self) -> str:
        return self._p(".staging")

    @property
    def version_path(self) -> str:
        return self._p("VERSION.json")

    @property
    def state_path(self) -> str:
        return self._p("update-state.json")

    # --- status ---------------------------------------------------------------
    def installed(self) -> dict:
        return read_json(self.version_path) or {}

    def problem(self) -> str | None:
        """Waarom updaten via de website hier niet kan, of None."""
        if not REPO_RE.match(self.repo):
            return "Er is geen geldige GitHub-repository ingesteld (update_repo in config.json)."
        if os.path.exists(self._p(".git")):
            return "Dit is een ontwikkelmap met git. Werk die bij met git pull."
        if not (os.access(self.app_dir, os.W_OK) and os.access(self.current_dir, os.W_OK)):
            return (f"De programmamap {self.app_dir} is niet schrijfbaar voor deze gebruiker. "
                    "Voer op de kiosk eenmalig sudo ./install.sh opnieuw uit.")
        if self.require_systemd and "INVOCATION_ID" not in os.environ:
            return "Kiosk Player draait niet als systemd-dienst en kan zichzelf daarom niet herstarten."
        return None

    def status(self) -> dict:
        with self.lock:
            job = dict(self.job)
        return {
            "repo": self.repo,
            "installed": self.installed(),
            "job": job,
            "problem": self.problem(),
            "rollback_available": os.path.isdir(self.prev_dir),
            "last": read_json(self.state_path),
        }

    # --- GitHub ---------------------------------------------------------------
    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        headers = {"User-Agent": "kiosk-player-updater", "Accept": accept}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise UpdateError("Niet gevonden op GitHub. Bestaat de repository of branch nog?", 502)
            if exc.code in (403, 429):
                raise UpdateError("GitHub weigert het verzoek, waarschijnlijk door de limiet van "
                                  "60 verzoeken per uur. Probeer het later opnieuw.", 502)
            raise UpdateError(f"GitHub gaf foutcode {exc.code}", 502)
        except (urllib.error.URLError, OSError):
            raise UpdateError("GitHub is niet bereikbaar. Heeft de kiosk internet?", 502)

    def _get(self, url: str, limit: int = 2 * 1024 ** 2) -> bytes:
        with self._request(url) as resp:
            data = resp.read(limit + 1)
        if len(data) > limit:
            raise UpdateError("Antwoord van GitHub is te groot", 502)
        return data

    def _api(self, path: str, cache: bool = True):
        hit = self._cache.get(path)
        if cache and hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            data = json.loads(self._get(GITHUB_API + path).decode("utf-8"))
        except ValueError:
            raise UpdateError("Onleesbaar antwoord van GitHub", 502)
        if len(self._cache) > 200:
            self._cache.clear()
        self._cache[path] = (time.time(), data)
        return data

    def _download(self, url: str, dest: str) -> None:
        total = 0
        with self._request(url, accept="application/octet-stream") as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise UpdateError("De download is groter dan 50 MB en wordt geweigerd")
                f.write(chunk)

    def branches(self, fresh: bool = False) -> dict:
        repo = self._api(f"/repos/{self.repo}", cache=not fresh)
        items = self._api(f"/repos/{self.repo}/branches?per_page=100", cache=not fresh)
        if not isinstance(items, list):
            raise UpdateError("Onleesbaar antwoord van GitHub", 502)
        default = repo.get("default_branch") if isinstance(repo, dict) else None
        out = [{"name": b["name"], "sha": (b.get("commit") or {}).get("sha")}
               for b in items if isinstance(b, dict) and b.get("name")]
        out.sort(key=lambda b: (b["name"] != default, b["name"].lower()))
        return {"repo": self.repo, "default": default, "branches": out}

    def _branch_sha(self, branch: str, fresh: bool = False) -> str:
        if not isinstance(branch, str) or not branch:
            raise UpdateError("Kies een branch")
        for b in self.branches(fresh=fresh)["branches"]:
            if b["name"] == branch and b["sha"] and SHA_RE.match(b["sha"]):
                return b["sha"]
        raise UpdateError(f"Branch '{branch}' bestaat niet (meer) op GitHub", 404)

    def commit(self, branch: str) -> dict:
        sha = self._branch_sha(branch)
        info = commit_summary(self._api(f"/repos/{self.repo}/commits/{sha}"))
        info["branch"] = branch
        installed = self.installed().get("sha")
        info["same"] = installed == sha
        info["compare"] = None
        if installed and not info["same"] and SHA_RE.match(installed):
            try:
                cmp = self._api(f"/repos/{self.repo}/compare/{installed}...{sha}")
                info["compare"] = {"status": cmp.get("status"), "ahead_by": cmp.get("ahead_by"),
                                   "behind_by": cmp.get("behind_by")}
            except UpdateError:
                pass  # geïnstalleerde commit staat niet (meer) op GitHub
        return info

    # --- bijwerken ------------------------------------------------------------
    def _begin(self, **job) -> None:
        problem = self.problem()
        if problem:
            raise UpdateError(problem, 409)
        with self.lock:
            if self.job.get("status") in ("busy", "restarting"):
                raise UpdateError("Er loopt al een update", 409)
            self.job = {"status": "busy", "step": "Voorbereiden", "started": now_iso(), **job}

    def _step(self, message: str) -> None:
        with self.lock:
            self.job["step"] = message
        log.info("Update: %s", message)

    def start(self, branch: str, wait: bool = False) -> None:
        if not isinstance(branch, str) or not branch.strip():
            raise UpdateError("Kies een branch")
        self._begin(branch=branch, action="update")
        t = threading.Thread(target=self._run, args=(branch,), name="updater", daemon=True)
        t.start()
        if wait:
            t.join()

    def _run(self, branch: str) -> None:
        try:
            self._step("Versie opzoeken op GitHub")
            sha = self._branch_sha(branch, fresh=True)
            info = commit_summary(self._api(f"/repos/{self.repo}/commits/{sha}"))
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            os.makedirs(self.staging_dir)
            self._step("Downloaden")
            archive = os.path.join(self.staging_dir, "bron.tar.gz")
            self._download(f"{CODELOAD}/{self.repo}/tar.gz/{sha}", archive)
            self._step("Uitpakken")
            root = self._extract(archive, os.path.join(self.staging_dir, "bron"))
            self._step("Controleren")
            self.verify(root)
            self._step("Installeren")
            self._install(os.path.join(root, "app"), dict(info, branch=branch, sha=sha))
            with self.lock:
                self.job = dict(self.job, status="restarting", step="Kiosk Player herstart",
                                target_sha=sha)
            self.event("info", f"Bijgewerkt naar {branch} ({sha[:7]}). Kiosk Player herstart.")
            self.restart_cb()
        except UpdateError as exc:
            self._failed(str(exc))
        except Exception as exc:  # noqa: BLE001 - de melding moet in de interface komen
            log.exception("Update mislukt")
            self._failed(f"Onverwachte fout: {exc}")
        finally:
            if self.job.get("status") != "restarting":
                shutil.rmtree(self.staging_dir, ignore_errors=True)

    def _failed(self, message: str) -> None:
        with self.lock:
            self.job = dict(self.job, status="error", error=message, step=None)
        self.event("error", f"Update mislukt: {message}")

    @staticmethod
    def _extract(archive: str, dest: str) -> str:
        os.makedirs(dest)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(dest, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise UpdateError(f"Het archief van GitHub is ongeldig: {exc}")
        entries = [e for e in os.listdir(dest) if os.path.isdir(os.path.join(dest, e))]
        if len(entries) != 1:
            raise UpdateError("Het archief van GitHub heeft een onverwachte indeling")
        return os.path.join(dest, entries[0])

    @staticmethod
    def verify(root: str) -> None:
        """Controleer een uitgepakte versie voordat die de draaiende versie vervangt."""
        for rel in REQUIRED:
            if not os.path.isfile(os.path.join(root, *rel.split("/"))):
                raise UpdateError(f"Deze versie is geen geldige Kiosk Player: {rel} ontbreekt")
        if not os.path.isfile(os.path.join(root, "app", "updater.py")):
            raise UpdateError("Deze versie heeft nog geen update via de website. "
                              "Installeer hem met install.sh als je hem echt wilt.")
        app_dir = os.path.join(root, "app")
        for folder, _dirs, files in os.walk(app_dir):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                try:
                    with open(path, "rb") as f:
                        compile(f.read(), path, "exec")
                except SyntaxError as exc:
                    rel = os.path.relpath(path, root).replace(os.sep, "/")
                    raise UpdateError(f"Fout in {rel} (regel {exc.lineno}): {exc.msg}")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        try:
            res = subprocess.run(
                [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import app.server", root],
                cwd=root, env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            raise UpdateError("De nieuwe versie laden duurde te lang")
        if res.returncode != 0:
            lines = [ln for ln in (res.stderr or "").strip().splitlines() if ln.strip()]
            raise UpdateError("De nieuwe versie kan niet geladen worden: " + (lines[-1] if lines else "onbekende fout"))

    def _install(self, new_app: str, info: dict) -> None:
        shutil.rmtree(self.prev_dir, ignore_errors=True)
        shutil.rmtree(self._p("app.failed"), ignore_errors=True)
        os.rename(self.current_dir, self.prev_dir)
        try:
            os.rename(new_app, self.current_dir)
        except OSError:
            os.rename(self.prev_dir, self.current_dir)
            raise
        old = self.installed()
        old.pop("previous", None)
        atomic_write_json(self.version_path, {
            "source": "github", "repo": self.repo, "branch": info.get("branch"), "sha": info.get("sha"),
            "message": info.get("message"), "date": info.get("date"), "installed_at": now_iso(),
            "previous": old or None,
        })
        atomic_write_json(self.state_path, {"status": "trial", "attempts": 0, "branch": info.get("branch"),
                                            "sha": info.get("sha"), "at": now_iso()})

    # --- terugzetten ------------------------------------------------------------
    def rollback(self) -> None:
        if not os.path.isdir(self.prev_dir):
            raise UpdateError("Er is geen vorige versie bewaard", 404)
        self._begin(action="rollback")
        try:
            tmp = self._p("app.swap")
            shutil.rmtree(tmp, ignore_errors=True)
            os.rename(self.current_dir, tmp)
            os.rename(self.prev_dir, self.current_dir)
            os.rename(tmp, self.prev_dir)
            cur = self.installed()
            prev = cur.pop("previous", None) or {"source": "onbekend"}
            atomic_write_json(self.version_path, dict(prev, installed_at=now_iso(), previous=cur or None))
            atomic_write_json(self.state_path, {"status": "manual_rollback", "at": now_iso(),
                                                "branch": prev.get("branch"), "sha": prev.get("sha")})
        except OSError as exc:
            self._failed(f"Terugzetten mislukt: {exc}")
            raise UpdateError(f"Terugzetten mislukt: {exc}", 500)
        with self.lock:
            self.job = dict(self.job, status="restarting", step="Kiosk Player herstart")
        self.event("info", "Vorige versie teruggezet. Kiosk Player herstart.")
        self.restart_cb()
