"""Check and install a published server release from the production host."""

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path
from time import monotonic
from urllib.error import HTTPError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from compose_update import Compose, UpdateError, prepare
from github_release import GitHubRelease
from release_bundle import DISK_RESERVE, OVERLAYS, unpack, version
from release_report import enqueue, flush, new_record, status_snapshot
from release_signature import payload, verify


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, state):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    if hasattr(os, "O_DIRECTORY"):
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def in_window(window, clock=None):
    if not window:
        return False
    if window == {"mode": "immediate"}:
        return True
    zone = dt.UTC if window["timezone"] == "UTC" else ZoneInfo(window["timezone"])
    now = (clock or dt.datetime.now(zone)).astimezone(zone).time()
    start, end = (dt.time.fromisoformat(window[key]) for key in ("start", "end"))
    if start == end or start.tzinfo or end.tzinfo:
        raise ValueError("Invalid maintenance window")
    return start <= now < end if start < end else now >= start or now < end


def trusted_local_path(path):
    owner = os.geteuid()
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise UpdateError(
                "Updater files must have a trusted owner, path and permissions"
            )


def stage(client, tag, asset, root):
    directory = root / tag
    if directory.exists():
        if (directory / "asset-digest").read_text() != asset["digest"]:
            raise UpdateError("Published asset changed after staging")
        if (directory / "images.tar").is_file():
            return directory
    for old in root.iterdir():
        if not old.is_dir() or old.is_symlink() or not (old / "asset-digest").is_file():
            continue
        try:
            superseded = version(old.name) < version(tag)
        except ValueError:
            continue
        if superseded:
            (old / "images.tar").unlink(missing_ok=True)
    if shutil.disk_usage(root).free < asset["size"] + DISK_RESERVE:
        raise UpdateError("Insufficient space to download the server release")
    with tempfile.TemporaryDirectory(prefix=".incoming-", dir=root) as work:
        staging = Path(work) / "stage"
        staging.mkdir()
        archive = Path(work) / "download.tar.gz"
        client.download(asset, archive)
        unpack(archive, staging, tag)
        (staging / "asset-digest").write_text(asset["digest"])
        if directory.exists():
            (staging / "images.tar").replace(directory / "images.tar")
        else:
            staging.rename(directory)
    print(f"Staged {tag}", flush=True)
    return directory


def recover(settings, state_path, state):
    tag = state["pending"]
    print(f"Restoring previous application release after interrupted {tag}", flush=True)
    previous = Compose(settings, state["active_dir"])
    previous.restart()
    state.update(pending=None, blocked=tag)
    if "report" in state:
        state["report"]["outcome"] = "Выполнен откат"
    save(state_path, state)
    try:
        previous.health(previous.config())
    except (UpdateError, OSError, ValueError, KeyError):
        print(
            "Previous containers are running, but public HTTPS needs attention",
            flush=True,
        )
        return False
    return True


def verify_offer(client, settings, tag, asset):
    key = Path(settings["release_public_key"]).absolute()
    if platform.system() == "Linux":
        trusted_local_path(key)
    data = payload(settings["repository"], tag, asset["digest"])
    with tempfile.TemporaryDirectory() as work:
        signature = Path(work) / "release.sig"
        client.download(asset["signature"], signature)
        verify(key, data, signature)


def report_finish(root, settings, state, record, started, https, failure=None):
    record["after"] = state["installed"]
    record["duration_seconds"] = round(monotonic() - started)
    failure_path = root / "last-reported-failure.json"
    if failure is not None:
        try:
            if read_json(failure_path) == failure:
                return
        except (OSError, ValueError):
            pass
    try:
        record["metrics"] = status_snapshot(
            root, Compose(settings, state["active_dir"]), https
        )
    except (UpdateError, OSError, ValueError, KeyError):
        print("Unable to collect deployment metrics", flush=True)
    try:
        enqueue(root, record)
        if failure is not None:
            save(failure_path, failure)
        if state.get("pending") is None and "report" in state:
            new_state = {key: value for key, value in state.items() if key != "report"}
            save(root / "state.json", new_state)
            state.pop("report")
    except OSError:
        print("Unable to queue deployment report", flush=True)


def apply_release(client, settings, root, state, tag, asset, record):
    state_path = root / "state.json"
    started = monotonic()
    https = None
    failure = None
    try:
        if settings.get("release_public_key"):
            verify_offer(client, settings, tag, asset)
            cached = root / tag
            if cached.exists() or cached.is_symlink():
                trusted_local_path(cached)
                for entry in cached.rglob("*"):
                    trusted_local_path(entry)
        if platform.system() != "Linux" or platform.machine().lower() not in (
            "x86_64",
            "amd64",
        ):
            raise UpdateError("Server releases require Linux amd64")
        ready = stage(client, tag, asset, root)
        if not in_window(settings.get("maintenance")):
            print("Waiting for a configured maintenance window", flush=True)
            record = None
            return
        current = Compose(settings, state["active_dir"])
        candidate = Compose(settings, ready)
        prepare(current, candidate, tag, ready)
        if not in_window(settings.get("maintenance")):
            print("Maintenance window closed during preparation", flush=True)
            record = None
            return
        state["pending"] = tag
        if record is not None:
            state["report"] = record
        save(state_path, state)
        try:
            current.stop_writers()
            backup = current.backup()
            if record is not None:
                record.update(backup=backup, outcome="Запуск новой версии")
                save(state_path, state)
            candidate.restart()
            candidate.health(candidate.config())
        except (UpdateError, OSError, ValueError, KeyError):
            if record is not None:
                record["outcome"] = "Требуется восстановление"
            https = recover(settings, state_path, state)
            if record is not None:
                record["outcome"] = "Выполнен откат"
            raise
        https = True
        installed = dict(
            state, active_dir=str(ready), installed=tag, pending=None, blocked=None
        )
        if record is not None:
            installed["report"] = dict(record, outcome="Установлен")
        save(state_path, installed)
        state.update(installed)
        if record is not None:
            record["outcome"] = "Установлен"
        print(f"Installed {tag}", flush=True)
        try:
            (ready / "images.tar").unlink(missing_ok=True)
        except OSError:
            print("Could not remove the installed release's image archive", flush=True)
    except (UpdateError, OSError, ValueError, KeyError) as error:
        if record is not None and record["outcome"] == "Остановка до переключения":
            failure = {
                "tag": tag,
                "digest": asset.get("digest"),
                "signature": asset.get("signature", {}).get("digest"),
                "cause": str(error)
                if isinstance(error, (UpdateError, ValueError))
                else type(error).__name__,
            }
        raise
    finally:
        if record is not None:
            report_finish(root, settings, state, record, started, https, failure)


def update(settings, root, check_only):
    overlays = settings.get("overlays", [])
    if not isinstance(overlays, list) or any(name not in OVERLAYS for name in overlays):
        raise ValueError("Unsupported Compose overlay")
    settings["overlays"] = overlays
    initial = settings.get("initial_version", "v0.0.0")
    version(initial)
    state_path = root / "state.json"
    state = (
        read_json(state_path)
        if state_path.exists()
        else {
            "active_dir": settings["initial_dir"],
            "installed": initial,
            "blocked": None,
            "pending": None,
        }
    )
    signed = bool(settings.get("release_public_key"))
    if state["pending"]:
        if check_only:
            raise UpdateError("A previous update needs local recovery")
        record = state.get("report")
        if record is None and settings.get("mail_reports"):
            record = new_record(state["pending"], state["installed"])
        started = monotonic()
        https = None
        try:
            if record is not None:
                record["outcome"] = "Требуется восстановление"
            https = recover(settings, state_path, state)
            if record is not None:
                record["outcome"] = "Выполнен откат после прерывания"
        finally:
            if record is not None:
                report_finish(root, settings, state, record, started, https)
        return
    if not check_only and (record := state.get("report")) is not None:
        report_finish(root, settings, state, record, monotonic(), None)
    if settings.get("maintenance") == {"mode": "immediate"} and not signed:
        raise UpdateError("Immediate updates require a trusted release signing key")
    client = GitHubRelease(settings["repository"], os.getenv("REGSYS_GITHUB_TOKEN"))
    options = {"require_signature": True} if signed else {}
    latest = client.latest(state["installed"], state["blocked"], **options)
    if not latest:
        print("No new eligible server release")
        return
    tag, asset = latest
    print(f"Eligible release: {tag}", flush=True)
    if check_only:
        if signed:
            verify_offer(client, settings, tag, asset)
        return
    record = (
        new_record(tag, state["installed"]) if settings.get("mail_reports") else None
    )
    apply_release(client, settings, root, state, tag, asset, record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Query GitHub without staging or applying an update",
    )
    mode.add_argument(
        "--send-test", action="store_true", help="Send a test report without deploying"
    )
    args = parser.parse_args()
    try:
        if platform.system() == "Linux":
            trusted_local_path(args.config.absolute())
        settings = read_json(args.config)
        root = Path(settings["state_dir"]).absolute()
        if platform.system() == "Linux":
            trusted_local_path(root.parent)
            if root.exists() or root.is_symlink():
                trusted_local_path(root)
        if args.check:
            update(settings, root, True)
            return 0
        import fcntl

        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.stat().st_mode & 0o077:
            raise UpdateError("Updater state directory must be private")
        with (root / "update.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Update already running")
                return 0
            if args.send_test:
                record = new_record("Проверка почты", "—")
                record["outcome"] = "Тестовое письмо"
                enqueue(root, record)
                return 0 if flush(root) else 1
            try:
                update(settings, root, False)
            finally:
                if settings.get("mail_reports"):
                    flush(root)
    except HTTPError as error:
        print(f"GitHub request failed (HTTP {error.code})", flush=True)
        return 1
    except UpdateError as error:
        print(str(error), flush=True)
        return 1
    except (
        OSError,
        ImportError,
        KeyError,
        TypeError,
        ValueError,
        tarfile.TarError,
        ZoneInfoNotFoundError,
    ) as error:
        print(f"Server update stopped ({type(error).__name__})", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
