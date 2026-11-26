import datetime as dt
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import Request

import update as updater
from compose_update import Compose, UpdateError, prepare
from github_release import GitHubRedirect, GitHubRelease
from release_bundle import (
    ASSET,
    CONFIG_FILES,
    image_names,
    pack,
    unpack,
    verify_image_tags,
)


class ReleaseTests(unittest.TestCase):
    def test_reads_only_new_stable_server_release(self):
        service = GitHubRelease("team/project")
        asset = {
            "name": ASSET,
            "id": 20,
            "state": "uploaded",
            "size": 1,
            "digest": "sha256:" + "0" * 64,
        }
        valid = {"draft": False, "prerelease": False, "tag_name": "v1.1.0", "assets": [asset]}
        cases = (
            ({}, "v1.0.0", None, ("v1.1.0", asset)),
            ({"draft": True}, "v1.0.0", None, None),
            ({"prerelease": True}, "v1.0.0", None, None),
            ({"assets": []}, "v1.0.0", None, None),
            ({"tag_name": "main"}, "v1.0.0", None, None),
            ({}, "v1.1.0", None, None),
            ({}, "v2.0.0", None, None),
            ({}, "v1.0.0", "v1.1.0", None),
        )
        for changes, installed, blocked, expected in cases:
            with (
                self.subTest(changes=changes, installed=installed, blocked=blocked),
                patch.object(
                    service,
                    "request",
                    return_value=io.BytesIO(json.dumps(valid | changes).encode()),
                ),
            ):
                self.assertEqual(service.latest(installed, blocked), expected)

    def test_download_checks_size_and_digest(self):
        service = GitHubRelease("team/project")
        data = b"archive bytes"
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / "archive"
            asset = {
                "id": 1,
                "size": len(data),
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            }
            with patch.object(service, "request", return_value=io.BytesIO(data)):
                service.download(asset, target)
            self.assertEqual(target.read_bytes(), data)
            with (
                patch.object(service, "request", return_value=io.BytesIO(data[:-1])),
                self.assertRaises(ValueError),
            ):
                service.download(asset, target.with_name("truncated"))
            with (
                patch.object(service, "request", return_value=io.BytesIO(b"0" * len(data))),
                self.assertRaises(ValueError),
            ):
                service.download(asset, target.with_name("corrupt"))

    def test_api_token_is_not_forwarded_to_asset_host(self):
        request = Request("https://api.github.com/repos/team/project/releases/assets/1")
        request.add_unredirected_header("Authorization", "Bearer test")
        redirect = GitHubRedirect()
        next_request = redirect.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://release-assets.githubusercontent.com/file",
        )
        self.assertIsNone(next_request.get_header("Authorization"))
        with self.assertRaises(ValueError):
            redirect.redirect_request(request, None, 302, "Found", {}, "https://example.org/file")

    def test_archive_round_trip_and_image_names(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for name in CONFIG_FILES:
                path = root / name
                path.parent.mkdir(exist_ok=True)
                path.write_text(name)
            payload = json.dumps([{"RepoTags": list(image_names("v1.0.0").values())}]).encode()
            images = root / "images.tar"
            with tarfile.open(images, "w:") as archive:
                member = tarfile.TarInfo("manifest.json")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            asset = root / ASSET
            pack(
                root,
                images,
                {"version": "v1.0.0", "commit": "a" * 40, "platform": "linux/amd64"},
                asset,
            )
            unpack(asset, root / "next", "v1.0.0")
            verify_image_tags(root / "next" / "images.tar", "v1.0.0")
            with self.assertRaises(ValueError):
                verify_image_tags(root / "next" / "images.tar", "v2.0.0")

    def test_archive_rejects_unexpected_paths(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            asset = root / ASSET
            with tarfile.open(asset, "w:gz") as archive:
                item = tarfile.TarInfo("../outside")
                item.size = 1
                archive.addfile(item, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                unpack(asset, root / "next", "v1.0.0")
            self.assertFalse((root / "outside").exists())


class InstallationTests(unittest.TestCase):
    def test_baseline_uses_the_compose_hash_wildcard(self):
        baseline = Compose.__new__(Compose)
        baseline.files = ["/opt/regsys/docker-compose.prod.yml"]
        config = {"services": {name: {} for name in ("api", "backup", "edge")}}
        labels = json.dumps(
            {
                "com.docker.compose.project.config_files": baseline.files[0],
                "com.docker.compose.config-hash": "a" * 64,
            }
        )

        def compose_call(_label, *args):
            if args[0] == "config":
                self.assertEqual(args, ("config", "--hash=*"))
                return "\n".join(f"{name} {'a' * 64}" for name in config["services"])
            return "b" * 12

        with (
            patch.object(baseline, "call", side_effect=compose_call),
            patch(
                "compose_update.run", side_effect=["sha256:fixture", "sha256:fixture", labels] * 3
            ),
        ):
            baseline.verify_baseline(config)

    def test_window_crosses_midnight_and_can_be_disabled(self):
        time = dt.datetime(2026, 1, 1, 23, tzinfo=dt.UTC)
        self.assertTrue(
            updater.in_window({"timezone": "UTC", "start": "22:00", "end": "01:00"}, time)
        )
        self.assertFalse(
            updater.in_window({"timezone": "UTC", "start": "01:00", "end": "02:00"}, time)
        )
        self.assertFalse(updater.in_window(None, time))

    def test_pending_migrations_do_not_reach_switch(self):
        current, candidate = Mock(), Mock()
        images = image_names("v1.0.0")
        config = {"volumes": {}, "networks": {}, "services": {"db": {}}}
        config["services"].update(
            {name: {"image": image, "environment": {}} for name, image in images.items()}
        )
        current.config.return_value = candidate.config.return_value = config
        current.revisions.return_value = {"old-head"}
        current.call.return_value = "old-head"
        with (
            patch("compose_update.verify_image_tags"),
            patch("compose_update.check_image_disk_space"),
            patch("compose_update.run", side_effect=["", "new-head"]),
            self.assertRaisesRegex(UpdateError, "needs a database migration"),
        ):
            prepare(current, candidate, "v1.0.0", Path("stage"))
        current.stop_writers.assert_not_called()

    def test_installation_failure_restores_previous_release(self):
        for stage in ("backup", "candidate"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as work:
                self.assert_rolls_back(Path(work), stage)

    def assert_rolls_back(self, root, stage):
        old, new = Mock(), Mock()
        if stage == "backup":
            old.backup.side_effect = UpdateError("Bad backup")
        else:
            new.health.side_effect = UpdateError("Bad health check")
            old.health.side_effect = UpdateError("External network is still unavailable")
        config = {"initial_dir": "old", "repository": "team/project"}
        with (
            patch("update.GitHubRelease") as github,
            patch("update.platform.system", return_value="Linux"),
            patch("update.platform.machine", return_value="x86_64"),
            patch("update.stage", return_value=root / "candidate"),
            patch("update.in_window", return_value=True),
            patch("update.prepare"),
            patch("update.Compose", side_effect=[old, new, old]),
        ):
            github.return_value.latest.return_value = "v1.0.0", {}
            with self.assertRaises(UpdateError):
                updater.update(config, root, False)
        old.restart.assert_called_once()
        self.assertEqual(new.restart.call_count, int(stage == "candidate"))
        state = updater.read_json(root / "state.json")
        self.assertEqual(
            state,
            {"active_dir": "old", "installed": "v0.0.0", "blocked": "v1.0.0", "pending": None},
        )

    def test_installed_release_is_recorded_and_next_check_does_not_switch(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            ready = root / "candidate"
            ready.mkdir()
            (ready / "images.tar").write_bytes(b"loaded")
            config = {"initial_dir": "old", "repository": "team/project"}
            with (
                patch("update.GitHubRelease") as github,
                patch("update.platform.system", return_value="Linux"),
                patch("update.platform.machine", return_value="x86_64"),
                patch("update.stage", return_value=ready),
                patch("update.in_window", return_value=True),
                patch("update.prepare"),
                patch("update.Compose") as compose,
            ):
                github.return_value.latest.side_effect = [("v1.0.0", {}), None]
                updater.update(config, root, False)
                updater.update(config, root, False)
                github.return_value.latest.assert_called_with("v1.0.0", None)
            compose.return_value.restart.assert_called_once()
            self.assertEqual(updater.read_json(root / "state.json")["active_dir"], str(ready))
            self.assertFalse((ready / "images.tar").exists())


if __name__ == "__main__":
    unittest.main()
