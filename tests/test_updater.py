"""Tests voor de update via GitHub en het terugzetten in run.py, zonder netwerk."""
import importlib.util
import io
import json
import os
import sys
import tarfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.updater import Updater, UpdateError  # noqa: E402

SHA_MAIN = "a" * 40
SHA_TEST = "b" * 40
SHA_OLD = "c" * 40

GOOD_FILES = {
    "app/__init__.py": "",
    "app/server.py": "VERSION = 'nieuw'\n",
    "app/updater.py": "",
    "app/static/index.html": "<!doctype html>",
    "CHANGELOG.md": "# Changelog\n\n## Nieuw\n",
}


def tarball(files: dict, top: str = "Kiosk-player-abc") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGitHub(Updater):
    """Updater met nep-antwoorden van GitHub."""

    files = GOOD_FILES

    def _api(self, path, cache=True):
        if path.endswith("/branches?per_page=100"):
            return [{"name": "main", "commit": {"sha": SHA_MAIN}},
                    {"name": "test/nieuw", "commit": {"sha": SHA_TEST}}]
        if "/compare/" in path:
            return {"status": "ahead", "ahead_by": 3, "behind_by": 0}
        if "/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            return {"sha": sha, "html_url": "https://example.invalid",
                    "commit": {"message": f"Commit {sha[:3]}\n\nmeer tekst",
                               "committer": {"date": "2026-11-22T12:00:00Z"},
                               "author": {"name": "Ontwikkelaar"}}}
        return {"default_branch": "main"}

    def _download(self, url, dest):
        with open(dest, "wb") as f:
            f.write(tarball(self.files))

    raw_requests: list = []

    def _get(self, url, limit=2 * 1024 ** 2):
        self.raw_requests.append(url)
        if url.endswith(f"/{SHA_TEST}/CHANGELOG.md"):
            return "# Changelog\n\n- Iets nieuws\n".encode()
        raise UpdateError("Niet gevonden op GitHub", 502, not_found=True)


@pytest.fixture
def install(tmp_path):
    app = tmp_path / "app"
    (app / "static").mkdir(parents=True)
    (app / "server.py").write_text("VERSION = 'oud'\n")
    (tmp_path / "VERSION.json").write_text(json.dumps(
        {"source": "install.sh", "branch": "main", "sha": SHA_OLD, "installed_at": "2026-11-01T10:00:00"}))
    return tmp_path


def make(install, files=GOOD_FILES):
    restarts = []
    up = FakeGitHub(str(install), "eigenaar/Kiosk-player", restart=lambda: restarts.append(1),
                    require_systemd=False)
    up.files = files
    return up, restarts


def test_update_replaces_app_and_keeps_previous(install):
    up, restarts = make(install)
    up.start("test/nieuw", wait=True)
    assert up.job["status"] == "restarting", up.job
    assert restarts == [1]
    assert "nieuw" in (install / "app" / "server.py").read_text()
    assert "oud" in (install / "app.prev" / "server.py").read_text()
    version = json.loads((install / "VERSION.json").read_text())
    assert version["branch"] == "test/nieuw" and version["sha"] == SHA_TEST
    assert version["message"] == f"Commit {SHA_TEST[:3]}"
    assert version["previous"]["sha"] == SHA_OLD
    state = json.loads((install / "update-state.json").read_text())
    assert state["status"] == "trial" and state["sha"] == SHA_TEST
    # de changelog hoort bij de versie in app/, en gaat bij terugzetten mee
    assert "## Nieuw" in (install / "app" / "CHANGELOG.md").read_text()
    assert not (install / "app.prev" / "CHANGELOG.md").exists()


def test_changelog_of_branch(install):
    up, _ = make(install)
    up.raw_requests = []
    r = up.changelog("test/nieuw")
    assert r["sha"] == SHA_TEST and "Iets nieuws" in r["text"]
    up.changelog("test/nieuw")
    assert len(up.raw_requests) == 1  # per commit gecachet
    assert up.changelog("main")["text"] is None  # oudere versie zonder changelog
    with pytest.raises(UpdateError):
        up.changelog("bestaat-niet")


@pytest.mark.parametrize("files, message", [
    ({k: v for k, v in GOOD_FILES.items() if k != "app/updater.py"}, "nog geen update via de website"),
    ({k: v for k, v in GOOD_FILES.items() if k != "app/server.py"}, "server.py ontbreekt"),
    (dict(GOOD_FILES, **{"app/server.py": "def kapot(:\n"}), "Fout in app/server.py"),
    (dict(GOOD_FILES, **{"app/server.py": "import bestaat_niet_xyz\n"}), "kan niet geladen worden"),
])
def test_bad_version_is_refused_and_nothing_changes(install, files, message):
    up, restarts = make(install, files)
    up.start("main", wait=True)
    assert up.job["status"] == "error" and message in up.job["error"]
    assert restarts == []
    assert "oud" in (install / "app" / "server.py").read_text()
    assert not (install / "app.prev").exists()
    assert not (install / ".staging").exists()


def test_unknown_branch_is_refused(install):
    up, restarts = make(install)
    up.start("../../etc", wait=True)
    assert up.job["status"] == "error" and "bestaat niet" in up.job["error"]
    with pytest.raises(UpdateError):
        up.start("")
    assert restarts == []


def test_branches_and_commit_info(install):
    up, _ = make(install)
    br = up.branches()
    assert br["default"] == "main" and [b["name"] for b in br["branches"]] == ["main", "test/nieuw"]
    c = up.commit("main")
    assert c["sha"] == SHA_MAIN and not c["same"] and c["compare"]["ahead_by"] == 3


def test_problems_block_update(install):
    (install / ".git").mkdir()
    up, _ = make(install)
    assert "ontwikkelmap" in up.problem()
    with pytest.raises(UpdateError):
        up.start("main")
    up2 = Updater(str(install), "geen repo", require_systemd=False)
    os.rmdir(install / ".git")
    assert "repository" in up2.problem()


def test_manual_rollback_swaps_versions(install):
    up, restarts = make(install)
    up.start("test/nieuw", wait=True)
    up.job = {"status": "idle"}
    up.rollback()
    assert "oud" in (install / "app" / "server.py").read_text()
    assert "nieuw" in (install / "app.prev" / "server.py").read_text()
    version = json.loads((install / "VERSION.json").read_text())
    assert version["sha"] == SHA_OLD and version["previous"]["sha"] == SHA_TEST
    assert json.loads((install / "update-state.json").read_text())["status"] == "manual_rollback"
    assert restarts == [1, 1]


# --- run.py --------------------------------------------------------------------
def load_run():
    spec = importlib.util.spec_from_file_location("kiosk_run", os.path.join(ROOT, "run.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_guard_counts_attempts_then_rolls_back(install):
    up, _ = make(install)
    up.start("test/nieuw", wait=True)
    run = load_run()
    for attempt in range(1, run.MAX_ATTEMPTS + 1):
        assert run.guard_update(str(install), healthy_after=3600) == "trial"
        assert json.loads((install / "update-state.json").read_text())["attempts"] == attempt
    assert run.guard_update(str(install), healthy_after=3600) == "rolled_back"
    assert "oud" in (install / "app" / "server.py").read_text()
    assert "nieuw" in (install / "app.failed" / "server.py").read_text()
    state = json.loads((install / "update-state.json").read_text())
    assert state["status"] == "rolled_back" and state["failed_sha"] == SHA_TEST
    assert json.loads((install / "VERSION.json").read_text())["sha"] == SHA_OLD
    assert run.guard_update(str(install)) is None  # daarna gewoon starten


def test_run_guard_marks_healthy_version_ok(install):
    up, _ = make(install)
    up.start("main", wait=True)
    run = load_run()
    assert run.guard_update(str(install), healthy_after=0) == "trial"
    import time
    for _ in range(50):
        if json.loads((install / "update-state.json").read_text())["status"] == "ok":
            break
        time.sleep(0.05)
    assert json.loads((install / "update-state.json").read_text())["status"] == "ok"


def test_run_guard_ignores_normal_start(install):
    assert load_run().guard_update(str(install)) is None
