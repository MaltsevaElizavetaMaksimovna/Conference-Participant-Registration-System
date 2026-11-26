"""Check and install a published server release from the production host."""

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from compose_update import Compose, UpdateError, prepare
from github_release import GitHubRelease
from release_bundle import DISK_RESERVE, OVERLAYS, unpack, version


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
    zone = dt.UTC if window["timezone"] == "UTC" else ZoneInfo(window["timezone"])
    now = (clock or dt.datetime.now(zone)).astimezone(zone).time()
    start, end = (dt.time.fromisoformat(window[key]) for key in ("start", "end"))
    if start == end or start.tzinfo or end.tzinfo:
        raise ValueError("Invalid maintenance window")
    return start <= now < end if start < end else now >= start or now < end


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
    save(state_path, state)
    try:
        previous.health(previous.config())
    except (UpdateError, OSError, ValueError, KeyError):
        print("Previous containers are running, but public HTTPS needs attention", flush=True)


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
    if state["pending"]:
        if check_only:
            raise UpdateError("A previous update needs local recovery")
        recover(settings, state_path, state)
        return
    client = GitHubRelease(settings["repository"], os.getenv("REGSYS_GITHUB_TOKEN"))
    latest = client.latest(state["installed"], state["blocked"])
    if not latest:
        print("No new eligible server release")
        return
    tag, asset = latest
    print(f"Eligible release: {tag}", flush=True)
    if check_only:
        return
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise UpdateError("Server releases require Linux amd64")
    ready = stage(client, tag, asset, root)
    if not in_window(settings.get("maintenance")):
        print("Waiting for a configured maintenance window")
        return
    current = Compose(settings, state["active_dir"])
    candidate = Compose(settings, ready)
    prepare(current, candidate, tag, ready)
    if not in_window(settings.get("maintenance")):
        print("Maintenance window closed during preparation")
        return
    state["pending"] = tag
    save(state_path, state)
    try:
        current.stop_writers()
        current.backup()
        candidate.restart()
        candidate.health(candidate.config())
    except (UpdateError, OSError, ValueError, KeyError):
        recover(settings, state_path, state)
        raise
    state.update(active_dir=str(ready), installed=tag, pending=None, blocked=None)
    save(state_path, state)
    print(f"Installed {tag}", flush=True)
    try:
        (ready / "images.tar").unlink(missing_ok=True)
    except OSError:
        print("Could not remove the installed release's image archive", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--check", action="store_true", help="Query GitHub without staging or applying an update"
    )
    args = parser.parse_args()
    try:
        settings = read_json(args.config)
        root = Path(settings["state_dir"]).resolve()
        if args.check:
            update(settings, root, True)
            return 0
        import fcntl

        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (root / "update.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Update already running")
                return 0
            update(settings, root, False)
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
