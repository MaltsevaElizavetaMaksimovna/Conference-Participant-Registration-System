import datetime as dt
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import release_report as report
import release_signature as signature
import setup_notifications as setup
import update
from github_release import GitHubRelease
from release_bundle import ASSET

REPO = "team/project"
TAG = "v1.1.0"
DIGEST = "sha256:" + "a" * 64


class SignatureTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for Ed25519")
    def test_signature_binds_repository_tag_and_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            private, public, signed = (
                Path(folder) / name for name in ("key", "pub", "sig")
            )
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "Ed25519", "-out", str(private)],
                check=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-in",
                    str(private),
                    "-pubout",
                    "-out",
                    str(public),
                ],
                check=True,
            )
            data = signature.payload(REPO, TAG, DIGEST)
            result = signature.openssl("-sign", private, data)
            self.assertEqual(result.returncode, 0)
            signed.write_bytes(result.stdout)
            signature.verify(public, data, signed)
            for item in (
                signature.payload("other/project", TAG, DIGEST),
                signature.payload(REPO, "v1.2.0", DIGEST),
                signature.payload(REPO, TAG, "sha256:" + "b" * 64),
            ):
                with self.assertRaisesRegex(ValueError, "signature is invalid"):
                    signature.verify(public, item, signed)
            signed.write_bytes(bytes(signature.SIGNATURE_SIZE))
            with self.assertRaisesRegex(ValueError, "signature is invalid"):
                signature.verify(public, data, signed)

    def test_unsigned_candidate_is_ignored_in_signed_mode(self):
        service = GitHubRelease(REPO)
        asset = {
            "id": 1,
            "name": ASSET,
            "size": 100,
            "state": "uploaded",
            "digest": DIGEST,
        }
        sig = {
            **asset,
            "id": 2,
            "name": signature.SIGNATURE,
            "size": signature.SIGNATURE_SIZE,
        }
        release = {"draft": False, "prerelease": False, "tag_name": TAG}
        for assets, expected in (
            ([asset], None),
            ([asset, sig], (TAG, asset | {"signature": sig})),
        ):
            response = io.BytesIO(json.dumps(release | {"assets": assets}).encode())
            with patch.object(service, "request", return_value=response):
                self.assertEqual(
                    service.latest("v1.0.0", None, require_signature=True), expected
                )

    def test_invalid_signature_stops_before_staging(self):
        state = {"installed": "v1.0.0", "active_dir": "old", "pending": None}
        with (
            patch(
                "update.verify_offer",
                side_effect=ValueError("Release signature is invalid"),
            ),
            patch("update.stage") as stage,
            patch("update.prepare") as prepare,
            self.assertRaisesRegex(ValueError, "Release signature is invalid"),
        ):
            update.apply_release(
                Mock(),
                {"release_public_key": "key"},
                Path("state"),
                state,
                TAG,
                {},
                None,
            )
        stage.assert_not_called()
        prepare.assert_not_called()


class MailTests(unittest.TestCase):
    def test_no_new_release_does_not_queue_mail(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("update.GitHubRelease") as github,
            patch("update.enqueue") as enqueue,
        ):
            github.return_value.latest.return_value = None
            settings = {
                "repository": REPO,
                "initial_dir": "current",
                "mail_reports": True,
            }
            update.update(settings, Path(folder), False)
            enqueue.assert_not_called()

    def test_identical_preflight_failures_queue_one_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = {"installed": "v1.0.0", "active_dir": "current", "pending": None}
            settings = {"release_public_key": "key"}
            with (
                patch(
                    "update.verify_offer",
                    side_effect=ValueError("Release signature is invalid"),
                ),
                patch("update.Compose"),
                patch("update.status_snapshot", return_value={"HTTPS": "доступен"}),
            ):
                for digest in (DIGEST, DIGEST, "sha256:" + "b" * 64):
                    with self.assertRaises(ValueError):
                        update.apply_release(
                            Mock(),
                            settings,
                            root,
                            state,
                            TAG,
                            {"digest": digest},
                            report.new_record(TAG, state["installed"]),
                        )
            self.assertEqual(len(list((root / "mail-queue").glob("*.json"))), 2)

    def test_immediate_mode_has_no_time_cutoff(self):
        for hour in (0, 12, 23):
            clock = dt.datetime(2026, 1, 1, hour, tzinfo=dt.UTC)
            self.assertTrue(update.in_window({"mode": "immediate"}, clock))
            self.assertFalse(update.in_window(None, clock))

    def test_immediate_mode_requires_signing_key(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("update.GitHubRelease") as github,
        ):
            settings = {"initial_dir": "current", "maintenance": {"mode": "immediate"}}
            with self.assertRaisesRegex(
                update.UpdateError, "trusted release signing key"
            ):
                update.update(settings, Path(folder), False)
            github.assert_not_called()

    def test_queue_preserves_message_id_on_smtp_failure_and_skips_bad_item(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "mail-queue").mkdir()
            broken = root / "mail-queue" / "corrupt.json"
            broken.write_text("{", encoding="utf-8")
            record = report.new_record(TAG, "v1.0.0")
            report.enqueue(root, record)
            with patch.object(
                report, "deliver", side_effect=[OSError("offline"), None]
            ) as send:
                self.assertFalse(report.flush(root))
                self.assertTrue(report.flush(root))
            self.assertTrue(broken.with_suffix(".invalid").is_file())
            self.assertEqual(
                [call.args[0]["id"] for call in send.call_args_list], [record["id"]] * 2
            )
            self.assertFalse(list((root / "mail-queue").glob("*.json")))

    def test_apply_reports_success_and_rollback_with_verified_backup(self):
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                ready = root / TAG
                ready.mkdir()
                current, candidate = Mock(), Mock()
                current.backup.return_value = "regsys-20260101-010000.dump"
                if fails:
                    candidate.health.side_effect = update.UpdateError("HTTPS failure")
                settings = {"maintenance": {"mode": "immediate"}}
                state = {"installed": "v1.0.0", "active_dir": "old", "pending": None}
                record = report.new_record(TAG, state["installed"])
                with (
                    patch("update.platform.system", return_value="Linux"),
                    patch("update.platform.machine", return_value="x86_64"),
                    patch("update.stage", return_value=ready),
                    patch("update.prepare"),
                    patch(
                        "update.Compose",
                        side_effect=[current, candidate, current, current],
                    ),
                    patch(
                        "update.status_snapshot", return_value={"PostgreSQL": "healthy"}
                    ),
                ):
                    if fails:
                        with self.assertRaisesRegex(
                            update.UpdateError, "HTTPS failure"
                        ):
                            update.apply_release(
                                Mock(), settings, root, state, TAG, {}, record
                            )
                    else:
                        update.apply_release(
                            Mock(), settings, root, state, TAG, {}, record
                        )
                (queued,) = (root / "mail-queue").glob("*.json")
                outcome = "Выполнен откат" if fails else "Установлен"
                self.assertEqual(record["outcome"], outcome)
                self.assertEqual(record["after"], "v1.0.0" if fails else TAG)
                self.assertEqual(record["backup"], current.backup.return_value)
                self.assertEqual(json.loads(queued.read_text(encoding="utf-8")), record)
                self.assertNotIn("report", update.read_json(root / "state.json"))

    def test_yandex_smtp_uses_tls_and_recipient(self):
        record = report.new_record(TAG, "v1.0.0")
        settings = {
            "REGSYS_SMTP_HOST": "smtp.example.test",
            "REGSYS_SMTP_PORT": "465",
            "REGSYS_SMTP_FROM": "sender@example.test",
            "REGSYS_SMTP_TO": "recipient@example.test",
            "REGSYS_SMTP_USER": "sender",
            "REGSYS_SMTP_PASSWORD": "example-test",
        }
        with (
            patch.dict("os.environ", settings),
            patch.object(report.smtplib, "SMTP_SSL") as smtp,
        ):
            report.deliver(record)
        self.assertEqual(smtp.call_args.args, ("smtp.example.test", 465))
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[
            0
        ]
        self.assertEqual(message["To"], "recipient@example.test")
        self.assertEqual(message["Message-ID"], record["id"])
        self.assertIn(TAG, message.get_content())

    def test_setup_waits_for_test_delivery_and_preserves_install_state(self):
        for delivery_fails in (False, True):
            with (
                self.subTest(delivery_fails=delivery_fails),
                tempfile.TemporaryDirectory() as folder,
            ):
                root = Path(folder)
                config = root / "update.json"
                public = root / "source.pub"
                state = root / "state.json"
                config.write_text(
                    json.dumps({"state_dir": str(root), "maintenance": None})
                )
                state.write_text('{"installed":"v1.0.0","pending":null}')
                public.write_bytes(b"public key fixture")

                def run(args, *, fails=delivery_fails, **_kwargs):
                    if fails and args[0] == "systemd-run":
                        raise subprocess.CalledProcessError(1, args)

                with (
                    patch(
                        "sys.argv",
                        [
                            "setup",
                            "--public-key",
                            str(public),
                            "--recipient",
                            "to@example.test",
                        ],
                    ),
                    patch(
                        "setup_notifications.os.geteuid", return_value=0, create=True
                    ),
                    patch("setup_notifications.active_state", return_value="inactive"),
                    patch(
                        "setup_notifications.mail_settings",
                        return_value={"REGSYS_SMTP_USER": "fixture"},
                    ),
                    patch(
                        "setup_notifications.subprocess.run", side_effect=run
                    ) as command,
                    patch.multiple(
                        setup,
                        CONFIG=config,
                        MAIL=root / "mail.env",
                        KEY=root / "trusted.pub",
                        INSTALL=root,
                        UNITS=root,
                    ),
                ):
                    if delivery_fails:
                        with self.assertRaises(subprocess.CalledProcessError):
                            setup.main()
                    else:
                        setup.main()
                saved = json.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(
                    saved["maintenance"],
                    None if delivery_fails else {"mode": "immediate"},
                )
                self.assertEqual(
                    json.loads(state.read_text(encoding="utf-8"))["installed"], "v1.0.0"
                )
                self.assertTrue(
                    any(
                        "--send-test" in call.args[0] for call in command.call_args_list
                    )
                )
                self.assertFalse(
                    any("enable" in call.args[0] for call in command.call_args_list)
                )
