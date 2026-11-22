"""Kiosk Player — webinterface om VLC op een Ubuntu-kiosk te beheren."""
from __future__ import annotations

import getpass
import hashlib
import hmac
import logging
import logging.handlers
import os
import re
import secrets
import shlex
import socket
import sys
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import system
from .controller import Controller
from .media import ALLOWED_EXT, MediaLibrary, kind_of
from .player import Player
from .schedule import parse_hm, timeline
from .store import Config, Store, new_id
from .updater import Updater, UpdateError

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
log = logging.getLogger("kiosk")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# --------------------------------------------------------------------------
# validatie
# --------------------------------------------------------------------------
def _bool(value, default=False) -> bool:
    return bool(value) if value is not None else default


def _str(value, field, min_len=1, max_len=120) -> str:
    if not isinstance(value, str) or not (min_len <= len(value.strip()) <= max_len):
        raise ApiError(f"Veld '{field}' is ongeldig")
    return value.strip()


def _time(value, field) -> str:
    try:
        minutes = parse_hm(str(value))
    except (ValueError, AttributeError):
        raise ApiError(f"Ongeldige tijd bij '{field}'")
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ApiError(f"Ongeldige datum bij '{field}'")


def validate_queue(payload: dict, existing: dict | None = None) -> dict:
    q = dict(existing or {})
    q["name"] = _str(payload.get("name"), "naam", max_len=80)
    items = []
    for raw in payload.get("items") or []:
        name = raw.get("file") if isinstance(raw, dict) else None
        if not isinstance(name, str) or name != os.path.basename(name) or not kind_of(name):
            raise ApiError("Ongeldig bestand in wachtrij")
        item = {"file": name}
        if kind_of(name) == "image":
            dur = raw.get("duration")
            if dur not in (None, ""):
                try:
                    dur = int(dur)
                except (TypeError, ValueError):
                    raise ApiError(f"Ongeldige duur bij '{name}'")
                if not 1 <= dur <= 86400:
                    raise ApiError("Duur van een afbeelding moet tussen 1 en 86400 seconden liggen")
                item["duration"] = dur
        items.append(item)
    if len(items) > 500:
        raise ApiError("Maximaal 500 items per wachtrij")
    q["items"] = items
    q["loop"] = _bool(payload.get("loop"), True)
    q["shuffle"] = _bool(payload.get("shuffle"))
    q["mute"] = _bool(payload.get("mute"))
    q.setdefault("id", new_id())
    q.setdefault("created", time.time())
    q["updated"] = time.time()
    return q


def validate_rule(payload: dict, store: Store, existing: dict | None = None) -> dict:
    r = dict(existing or {})
    qid = payload.get("queue_id")
    if not store.queue(qid):
        raise ApiError("Kies een bestaande wachtrij")
    r["queue_id"] = qid
    r["name"] = (payload.get("name") or "").strip()[:80]
    days = payload.get("days")
    if not isinstance(days, list) or not days or not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
        raise ApiError("Kies minstens één dag")
    r["days"] = sorted(set(days))
    r["start"] = _time(payload.get("start"), "starttijd")
    r["end"] = _time(payload.get("end"), "eindtijd")
    r["date_from"] = _date(payload.get("date_from"), "vanaf")
    r["date_to"] = _date(payload.get("date_to"), "tot en met")
    if r["date_from"] and r["date_to"] and r["date_to"] < r["date_from"]:
        raise ApiError("De einddatum ligt vóór de begindatum")
    r["enabled"] = _bool(payload.get("enabled"), True)
    r.setdefault("id", new_id())
    r.setdefault("created", time.time())
    r["updated"] = time.time()
    return r


VLC_PROGRAMS = {"vlc", "cvlc"}
VLC_PROGRAM_DIRS = {"/usr/bin", "/usr/local/bin", "/snap/bin", "/bin"}
# Opties waarmee VLC andere code laadt, de interne bediening overneemt of bestanden wegschrijft.
BLOCKED_VLC_OPTIONS = ("--intf", "--extraintf", "--control", "--lua", "--http", "--plugin",
                       "--data-path", "--sout", "--snapshot-path", "--record-path",
                       "--input-record-path", "--config", "--logfile", "--file-logging")


def _vlc_options(tokens: list, field: str) -> None:
    for tok in tokens:
        if not tok.startswith("--"):
            raise ApiError(f"{field}: alleen opties die met -- beginnen zijn toegestaan ('{tok}')")
        name = tok.split("=", 1)[0].lower()
        if name.startswith("--no-"):
            name = "--" + name[5:]
        if any(name == b or name.startswith(b + "-") for b in BLOCKED_VLC_OPTIONS):
            raise ApiError(f"{field}: de optie '{name}' is niet toegestaan")


def validate_vlc_command(cmd: str) -> None:
    if system.IS_WINDOWS:
        prog = cmd.strip().strip('"')
        if prog.lower() in system.WINDOWS_VLC_NAMES or system.windows_vlc_path_allowed(prog):
            return
        raise ApiError("VLC-commando moet vlc zijn, of het volledige pad naar vlc.exe in een "
                       r"programmamap, zoals C:\Program Files\VideoLAN\VLC\vlc.exe")
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        raise ApiError("VLC-commando kan niet gelezen worden (controleer aanhalingstekens)")
    if not tokens:
        raise ApiError("Veld 'VLC-commando' is ongeldig")
    prog = tokens[0]
    folder, base = os.path.split(prog)
    if base not in VLC_PROGRAMS or (folder and folder not in VLC_PROGRAM_DIRS):
        raise ApiError("VLC-commando moet vlc of cvlc zijn, eventueel met een pad als /usr/bin/cvlc")
    _vlc_options(tokens[1:], "VLC-commando")


def validate_extra_args(extra: str) -> None:
    try:
        tokens = shlex.split(extra)
    except ValueError:
        raise ApiError("Extra VLC-opties kunnen niet gelezen worden (controleer aanhalingstekens)")
    _vlc_options(tokens, "Extra VLC-opties")


def validate_settings(payload: dict, store: Store) -> dict:
    out = {}
    if "default_queue" in payload:
        dq = payload["default_queue"] or None
        if dq and not store.queue(dq):
            raise ApiError("Onbekende standaardwachtrij")
        out["default_queue"] = dq
    for key in ("idle_black", "kill_other_vlc"):
        if key in payload:
            out[key] = bool(payload[key])
    if "vlc_command" in payload:
        cmd = _str(payload["vlc_command"], "VLC-commando", max_len=300)
        validate_vlc_command(cmd)
        out["vlc_command"] = cmd
    if "display" in payload:
        disp = _str(payload["display"], "display", max_len=40)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]*:\d+(\.\d+)?", disp):
            raise ApiError("Display moet er uitzien als :0")
        out["display"] = disp
    if "extra_args" in payload:
        extra = str(payload["extra_args"] or "").strip()
        if len(extra) > 500:
            raise ApiError("Extra VLC-opties zijn te lang (maximaal 500 tekens)")
        validate_extra_args(extra)
        out["extra_args"] = extra
    if "default_image_duration" in payload:
        try:
            v = int(payload["default_image_duration"])
        except (TypeError, ValueError):
            raise ApiError("Ongeldige standaardduur")
        if not 1 <= v <= 86400:
            raise ApiError("Standaardduur moet tussen 1 en 86400 seconden liggen")
        out["default_image_duration"] = v
    if "vlc_http_port" in payload:
        try:
            v = int(payload["vlc_http_port"])
        except (TypeError, ValueError):
            raise ApiError("Ongeldige poort")
        if not 1024 <= v <= 65535:
            raise ApiError("Poort moet tussen 1024 en 65535 liggen")
        out["vlc_http_port"] = v
    return out


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------
def create_app(data_dir: str) -> Flask:
    for sub in ("media", "thumbs", "logs"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)

    config = Config(data_dir)
    if not config["password_hash"]:
        pw = secrets.token_urlsafe(9)
        config["password_hash"] = generate_password_hash(pw)
        config.save()
        pw_file = os.path.join(data_dir, "EERSTE-WACHTWOORD.txt")
        with open(pw_file, "w") as f:
            f.write(pw + "\n")
        os.chmod(pw_file, 0o600)
        log.warning("Geen wachtwoord ingesteld. Tijdelijk wachtwoord staat in %s", pw_file)

    store = Store(data_dir)
    media = MediaLibrary(os.path.join(data_dir, "media"), os.path.join(data_dir, "thumbs"),
                         os.path.join(data_dir, "media.json"))
    player = Player(os.path.join(data_dir, "logs", "vlc.log"))
    controller = Controller(store, media, player, data_dir)

    def restart_process():
        """Stop VLC en beëindig het proces; systemd (Restart=always) start ons opnieuw."""
        def go():
            time.sleep(1.5)  # het antwoord en de laatste status nog laten ophalen
            try:
                with controller.tick_lock:
                    player.stop()
            finally:
                logging.shutdown()
                os._exit(0)
        threading.Thread(target=go, name="restart", daemon=True).start()

    updater = Updater(os.path.dirname(HERE), config["update_repo"], config["github_token"],
                      restart=restart_process, event=controller.event)

    app = Flask(__name__, static_folder=None)
    app.secret_key = config["secret_key"]
    app.config.update(
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_HTTPONLY=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=int(config["max_upload_gb"] * 1024 ** 3),
    )
    app.extensions["kiosk"] = {"config": config, "store": store, "media": media,
                               "player": player, "controller": controller, "data_dir": data_dir,
                               "updater": updater}
    failed_logins: dict = {}

    # --- beveiliging -------------------------------------------------------
    def pw_tag() -> str:
        """Verandert mee met het wachtwoord, zodat oude sessies dan ongeldig worden."""
        return hashlib.sha256((config["password_hash"] or "").encode()).hexdigest()[:16]

    def logged_in() -> bool:
        return bool(session.get("auth")) and hmac.compare_digest(str(session.get("pw", "")), pw_tag())

    @app.before_request
    def guard():
        path = request.path
        if path in ("/login", "/api/login") or path.startswith("/static/"):
            return None
        if not logged_in():
            session.clear()
            if path.startswith("/api/"):
                return jsonify(error="Niet ingelogd"), 401
            return redirect("/login")
        if path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
            if request.headers.get("X-Requested-With") != "kiosk":
                return jsonify(error="Verzoek geweigerd"), 403
        return None

    @app.errorhandler(ApiError)
    def api_error(err: ApiError):
        return jsonify(error=str(err), **err.extra), err.status

    @app.errorhandler(UpdateError)
    def update_error(err: UpdateError):
        return jsonify(error=str(err)), err.status

    @app.errorhandler(413)
    def too_large(_err):
        return jsonify(error=f"Bestand is groter dan {config['max_upload_gb']} GB"), 413

    def body() -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    # --- pagina's -------------------------------------------------------------
    def page(name):
        resp = send_from_directory(STATIC, name)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/")
    def index():
        return page("index.html")

    @app.get("/login")
    def login_page():
        if logged_in():
            return redirect("/")
        return page("login.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        resp = send_from_directory(STATIC, name)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.post("/api/login")
    def api_login():
        ip = request.remote_addr or "?"
        fails, until = failed_logins.get(ip, (0, 0))
        if until > time.time():
            return jsonify(error="Te veel pogingen. Probeer het over een minuut opnieuw."), 429
        pw = body().get("password") or ""
        if check_password_hash(config["password_hash"], pw):
            failed_logins.pop(ip, None)
            session.clear()
            session["auth"] = True
            session["pw"] = pw_tag()
            session.permanent = True
            return jsonify(ok=True)
        fails += 1
        failed_logins[ip] = (fails, time.time() + 60 if fails >= 5 else 0)
        time.sleep(0.8)
        return jsonify(error="Onjuist wachtwoord"), 401

    @app.post("/api/logout")
    def api_logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/password")
    def api_password():
        data = body()
        if not check_password_hash(config["password_hash"], data.get("current") or ""):
            raise ApiError("Huidig wachtwoord klopt niet")
        new = data.get("new") or ""
        if len(new) < 8:
            raise ApiError("Kies een wachtwoord van minstens 8 tekens")
        config["password_hash"] = generate_password_hash(new)
        config.save()
        session["pw"] = pw_tag()  # deze sessie blijft ingelogd, alle andere niet
        pw_file = os.path.join(data_dir, "EERSTE-WACHTWOORD.txt")
        if os.path.exists(pw_file):
            os.unlink(pw_file)
        return jsonify(ok=True)

    # --- status ---------------------------------------------------------------
    @app.get("/api/state")
    def api_state():
        return jsonify(controller.status())

    @app.get("/api/all")
    def api_all():
        snap = store.snapshot()
        return jsonify(queues=snap["queues"], rules=snap["rules"], settings=snap["settings"],
                       info={"version": VERSION, "data_dir": data_dir, "port": config["port"],
                             "max_upload_gb": config["max_upload_gb"],
                             "ffmpeg": bool(media.ffmpeg), "user": getpass.getuser(),
                             "platform": system.name(), "vlc": system.find_vlc()})

    @app.get("/api/events")
    def api_events():
        return jsonify(events=list(controller.events), vlc_log=player.log_tail(40))

    # --- media -------------------------------------------------------------------
    def usage_map() -> dict:
        used: dict = {}
        for q in store.queues:
            for it in q.get("items", []):
                used.setdefault(it["file"], set()).add(q["name"])
        return used

    @app.get("/api/media")
    def api_media():
        used = usage_map()
        items = media.list()
        for m in items:
            m["used_in"] = sorted(used.get(m["name"], []))
        return jsonify(media=items, disk=media.disk(), ffmpeg=bool(media.ffmpeg),
                       allowed=sorted(ALLOWED_EXT))

    @app.put("/api/media/upload")
    def api_upload():
        raw_name = urllib.parse.unquote(request.headers.get("X-Filename", ""))
        if not raw_name or not kind_of(raw_name):
            raise ApiError("Dit bestandstype wordt niet ondersteund. Gebruik video (mp4, mkv, mov, …) of afbeeldingen (png, jpg, …)")
        length = request.content_length
        if length is None:
            raise ApiError("Bestandsgrootte ontbreekt", 411)
        if media.disk()["free"] < length + 200 * 1024 ** 2:
            raise ApiError("Onvoldoende vrije schijfruimte op de kiosk", 507)
        name = media.unique_name(raw_name)
        part = os.path.join(media.media_dir, f".{name}.{secrets.token_hex(4)}.part")
        written = 0
        try:
            with open(part, "wb") as f:
                while True:
                    chunk = request.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
            if written != length:
                raise ApiError("Upload onvolledig ontvangen, probeer het opnieuw")
            os.replace(part, os.path.join(media.media_dir, name))
        finally:
            if os.path.exists(part):
                os.unlink(part)
        media.enqueue(name)
        controller.event("info", f"Geüpload: {name}")
        controller.poke()  # misschien maakt dit een wachtrij weer compleet
        return jsonify(ok=True, name=name)

    @app.delete("/api/media/<path:name>")
    def api_media_delete(name):
        if not media.path_for(name):
            raise ApiError("Bestand niet gevonden", 404)
        with store.lock:
            used = sorted(usage_map().get(name, []))
            if used and request.args.get("force") != "1":
                raise ApiError("Bestand wordt gebruikt", 409, used_in=used)
            for q in store.queues:
                q["items"] = [it for it in q.get("items", []) if it["file"] != name]
            store.save()
        playing = player.running and player.spec and any(
            os.path.basename(p) == name for p, _k, _d in player.spec.items)
        if playing:
            controller.tick()  # stop/herstart zonder dit bestand vóór het verwijderen
        media.delete(name)
        controller.event("info", f"Verwijderd: {name}")
        controller.poke()
        return jsonify(ok=True)

    @app.get("/media/<path:name>")
    def media_file(name):
        path = media.path_for(name)
        if not path:
            abort(404)
        return send_file(path, conditional=True)

    @app.get("/thumb/<path:name>")
    def media_thumb(name):
        if not media.path_for(name):
            abort(404)
        thumb = media.thumb_path(name)
        if not os.path.exists(thumb):
            abort(404)
        resp = send_file(thumb, conditional=True, max_age=300)
        return resp

    # --- wachtrijen -------------------------------------------------------------
    @app.get("/api/queues")
    def api_queues():
        return jsonify(queues=store.snapshot()["queues"])

    @app.post("/api/queues")
    def api_queue_create():
        with store.lock:
            q = validate_queue(body())
            store.queues.append(q)
            store.save()
        controller.event("info", f"Wachtrij aangemaakt: {q['name']}")
        return jsonify(queue=q)

    @app.put("/api/queues/<qid>")
    def api_queue_update(qid):
        with store.lock:
            existing = store.queue(qid)
            if not existing:
                raise ApiError("Wachtrij niet gevonden", 404)
            q = validate_queue(body(), existing)
            store.queues[store.queues.index(existing)] = q
            store.save()
        controller.poke()
        return jsonify(queue=q)

    @app.post("/api/queues/<qid>/duplicate")
    def api_queue_duplicate(qid):
        with store.lock:
            existing = store.queue(qid)
            if not existing:
                raise ApiError("Wachtrij niet gevonden", 404)
            copy_payload = dict(existing, name=f"{existing['name']} (kopie)"[:80])
            q = validate_queue(copy_payload)
            q["id"], q["created"] = new_id(), time.time()
            store.queues.append(q)
            store.save()
        return jsonify(queue=q)

    @app.delete("/api/queues/<qid>")
    def api_queue_delete(qid):
        with store.lock:
            existing = store.queue(qid)
            if not existing:
                raise ApiError("Wachtrij niet gevonden", 404)
            rules = [r for r in store.rules if r["queue_id"] == qid]
            is_default = store.settings.get("default_queue") == qid
            if (rules or is_default) and request.args.get("force") != "1":
                raise ApiError("Wachtrij wordt gebruikt", 409,
                               rules=[r.get("name") or "naamloze regel" for r in rules],
                               is_default=is_default)
            store.data["rules"] = [r for r in store.rules if r["queue_id"] != qid]
            if is_default:
                store.settings["default_queue"] = None
            store.queues.remove(existing)
            store.save()
        controller.event("info", f"Wachtrij verwijderd: {existing['name']}")
        controller.tick()
        return jsonify(ok=True)

    # --- schema -----------------------------------------------------------------
    @app.get("/api/rules")
    def api_rules():
        return jsonify(rules=store.snapshot()["rules"])

    @app.post("/api/rules")
    def api_rule_create():
        with store.lock:
            r = validate_rule(body(), store)
            store.rules.append(r)
            store.save()
        controller.poke()
        return jsonify(rule=r)

    @app.put("/api/rules/<rid>")
    def api_rule_update(rid):
        with store.lock:
            existing = store.rule(rid)
            if not existing:
                raise ApiError("Regel niet gevonden", 404)
            r = validate_rule(body(), store, existing)
            store.rules[store.rules.index(existing)] = r
            store.save()
        controller.poke()
        return jsonify(rule=r)

    @app.delete("/api/rules/<rid>")
    def api_rule_delete(rid):
        with store.lock:
            existing = store.rule(rid)
            if not existing:
                raise ApiError("Regel niet gevonden", 404)
            store.rules.remove(existing)
            store.save()
        controller.poke()
        return jsonify(ok=True)

    @app.get("/api/timeline")
    def api_timeline():
        try:
            start = date.fromisoformat(request.args.get("start") or date.today().isoformat())
            days = max(1, min(31, int(request.args.get("days", 7))))
        except ValueError:
            raise ApiError("Ongeldige periode")
        t0 = datetime.combine(start, datetime.min.time())
        with store.lock:
            s = store.settings
            if not s.get("scheduler_enabled", True):
                segs = []
            else:
                segs = timeline(store.rules, s.get("default_queue"), t0,
                                t0 + timedelta(days=days), store.queue_ids())
        return jsonify(start=t0.isoformat(), days=days, segments=[
            {"start": seg["start"].isoformat(), "end": seg["end"].isoformat(),
             "queue_id": seg["queue_id"], "rule_id": seg["rule_id"]} for seg in segs])

    # --- instellingen -----------------------------------------------------------
    @app.put("/api/settings")
    def api_settings():
        with store.lock:
            changes = validate_settings(body(), store)
            store.settings.update(changes)
            store.save()
        controller.event("info", "Instellingen opgeslagen")
        controller.tick()
        return jsonify(settings=store.snapshot()["settings"])

    @app.post("/api/scheduler")
    def api_scheduler():
        enabled = bool(body().get("enabled"))
        with store.lock:
            store.settings["scheduler_enabled"] = enabled
            store.save()
        controller.scheduler_toggled(enabled)
        return jsonify(ok=True)

    # --- speler -----------------------------------------------------------------
    @app.post("/api/player/<action>")
    def api_player(action):
        if action == "start":
            qid = body().get("queue_id")
            if not store.queue(qid):
                raise ApiError("Wachtrij niet gevonden", 404)
            controller.manual(qid)
        elif action == "stop":
            controller.manual(None)
        elif action == "resume":
            controller.resume_schedule()
        elif action == "restart":
            controller.restart()
        elif action in ("next", "prev", "pause", "play"):
            if not player.running:
                raise ApiError("VLC speelt nu niet")
            cmd = {"next": "pl_next", "prev": "pl_previous",
                   "pause": "pl_forcepause", "play": "pl_forceresume"}[action]
            if player.http(cmd) is None:
                raise ApiError("VLC reageert niet op de bediening (is de HTTP-interface van VLC beschikbaar?)", 502)
        else:
            raise ApiError("Onbekende actie", 404)
        return jsonify(ok=True)

    # --- software-update ---------------------------------------------------------
    @app.get("/api/update")
    def api_update_status():
        return jsonify(updater.status())

    @app.get("/api/update/branches")
    def api_update_branches():
        return jsonify(updater.branches())

    @app.get("/api/update/commit")
    def api_update_commit():
        return jsonify(updater.commit(request.args.get("branch", "")))

    @app.get("/api/update/changelog")
    def api_update_changelog():
        return jsonify(updater.changelog(request.args.get("branch", "")))

    @app.get("/api/changelog")
    def api_changelog():
        # Geïnstalleerd: app/CHANGELOG.md. In een ontwikkelmap: CHANGELOG.md naast app/.
        for path in (os.path.join(HERE, "CHANGELOG.md"), os.path.join(os.path.dirname(HERE), "CHANGELOG.md")):
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    return jsonify(text=f.read(), installed=updater.installed())
        return jsonify(text=None, installed=updater.installed())

    @app.post("/api/update")
    def api_update_start():
        updater.start(body().get("branch"))
        return jsonify(ok=True), 202

    @app.post("/api/update/rollback")
    def api_update_rollback():
        updater.rollback()
        return jsonify(ok=True), 202

    installed = updater.installed()
    label = f" ({installed.get('branch')} {str(installed.get('sha'))[:7]})" if installed.get("sha") else ""
    controller.event("info", f"Kiosk Player {VERSION}{label} gestart")
    controller.start()
    return app


# --------------------------------------------------------------------------
# opstarten
# --------------------------------------------------------------------------
def setup_logging(data_dir: str) -> None:
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    fileh = logging.handlers.RotatingFileHandler(
        os.path.join(data_dir, "logs", "kiosk-player.log"), maxBytes=1_000_000, backupCount=3)
    fileh.setFormatter(fmt)
    root.addHandler(fileh)


def data_dir_from_env() -> str:
    return os.path.abspath(os.environ.get("KIOSK_DATA_DIR") or os.path.expanduser("~/kiosk-player"))


def set_password(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    config = Config(data_dir)
    if sys.stdin.isatty():
        pw = getpass.getpass("Nieuw wachtwoord: ")
        if pw != getpass.getpass("Nogmaals: "):
            sys.exit("Wachtwoorden komen niet overeen.")
    else:
        # utf-8-sig: Windows PowerShell zet een BOM voor gepipete tekst
        pw = sys.stdin.buffer.readline().decode("utf-8-sig").rstrip("\r\n")
    if len(pw) < 8:
        sys.exit("Kies een wachtwoord van minstens 8 tekens.")
    config["password_hash"] = generate_password_hash(pw)
    config.save()
    print("Wachtwoord opgeslagen.")


def watch_supervisor(app: Flask) -> None:
    """Onder run.py --supervise: stop VLC en onszelf als de supervisor verdwijnt (stdin sluit dan)."""
    stdin = sys.stdin

    def wait_for_eof():
        try:
            if stdin is not None:
                stdin.buffer.read()
        except (OSError, ValueError):
            pass
        log.info("Supervisor is gestopt; Kiosk Player stopt ook")
        ext = app.extensions["kiosk"]
        try:
            with ext["controller"].tick_lock:
                ext["player"].stop()
        finally:
            logging.shutdown()
            os._exit(0)

    if stdin is not None:
        threading.Thread(target=wait_for_eof, name="supervisor-watch", daemon=True).start()


def main() -> None:
    data_dir = data_dir_from_env()
    if len(sys.argv) > 1 and sys.argv[1] == "set-password":
        set_password(data_dir)
        return
    if system.is_root() and os.environ.get("KIOSK_ALLOW_ROOT") != "1":
        sys.exit("Start Kiosk Player niet als root: VLC weigert als root te draaien. "
                 "Gebruik de kioskgebruiker (zie README).")
    os.makedirs(data_dir, exist_ok=True)
    config = Config(data_dir)
    host, port = config["host"], int(config["port"])
    # Vóór de planner start: een tweede exemplaar zou anders VLC van het eerste sluiten.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError:
        sys.exit(f"Poort {port} is al in gebruik. Draait Kiosk Player al?")
    setup_logging(data_dir)
    app = create_app(data_dir)
    if os.environ.get("KIOSK_SUPERVISED") == "1":
        watch_supervisor(app)
    log.info("Webinterface op http://%s:%s (data: %s, %s)", host, port, data_dir, system.name())
    try:
        from waitress import serve
    except ImportError:
        log.warning("waitress niet gevonden; ingebouwde server van Flask wordt gebruikt")
        app.run(host=host, port=port, threaded=True)
        return
    serve(app, host=host, port=port, threads=8, ident="kiosk-player",
          max_request_body_size=int(config["max_upload_gb"] * 1024 ** 3) + 1024 ** 2,
          channel_timeout=300)
