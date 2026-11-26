"""Apply a same-schema release using the existing production Compose project."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.request import HTTPRedirectHandler, build_opener

from release_bundle import DISK_RESERVE, SERVICES, image_names, verify_image_tags

HEADS = """
from alembic.script import ScriptDirectory
from app.cli import alembic_config
print(*ScriptDirectory.from_config(alembic_config()).get_heads(), sep='\\n')
"""
BACKUP = """
from zipfile import ZipFile
from scripts.backup import get_settings, make_backup, verify_backup
settings = get_settings()
files = make_backup(settings)
verify_backup(settings, files.dump)
with ZipFile(files.photos) as archive:
    if archive.testzip() is not None:
        raise RuntimeError('The new photo archive is damaged')
print(files.dump.name)
"""


class UpdateError(Exception):
    pass


def run(label, *args, timeout=180):
    env = {
        key: value for key, value in os.environ.items()
        if key != "REGSYS_GITHUB_TOKEN" and not key.startswith("REGSYS_SMTP_")
    }
    try:
        result = subprocess.run(
            args, capture_output=True, check=True, text=True, timeout=timeout, env=env
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise UpdateError(f"Failed stage: {label}") from error
    return result.stdout.strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Compose:
    def __init__(self, settings, directory):
        self.settings = settings
        directory = Path(directory).resolve(strict=True)
        command = [
            "docker",
            "compose",
            "--project-name",
            "regsys-prod",
            "--project-directory",
            str(directory),
        ]
        command += ["--env-file", str(Path(settings["env_file"]).resolve(strict=True))]
        self.files = []
        for name in ["docker-compose.prod.yml", *settings["overlays"], "release-images.json"]:
            file = directory / name
            if name != "release-images.json" or file.exists():
                resolved = str(file.resolve(strict=True))
                self.files.append(resolved)
                command += ["-f", resolved]
        self.command = command

    def call(self, label, *args, timeout=180):
        return run(label, *self.command, *args, timeout=timeout)

    def config(self):
        return json.loads(self.call("Compose configuration", "config", "--format", "json"))

    def revisions(self):
        current = self.call(
            "read database revision",
            "exec",
            "-T",
            "db",
            "psql",
            "-XAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "regsys",
            "-d",
            "regsys",
            "-c",
            "SELECT version_num FROM alembic_version",
        )
        return set(current.splitlines())

    def verify_baseline(self, config):
        hashes = dict(
            line.split()
            for line in self.call("read baseline hashes", "config", "--hash=*").splitlines()
        )
        for service in SERVICES:
            image = config["services"][service].get("image", f"regsys-prod-{service}")
            actual = self.call("locate running service", "ps", "-q", service)
            if not re.fullmatch(r"[0-9a-f]{12,64}", actual):
                raise UpdateError(f"Exactly one running {service} container is required")
            running = run(
                "inspect running service", "docker", "inspect", "--format", "{{.Image}}", actual
            )
            local = run(
                "inspect rollback image", "docker", "image", "inspect", "--format", "{{.Id}}", image
            )
            if running != local:
                raise UpdateError(
                    f"Rollback image for {service} differs from the running container"
                )
            labels = json.loads(
                run(
                    "inspect live Compose configuration",
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .Config.Labels}}",
                    actual,
                )
            )
            if (
                labels.get("com.docker.compose.project.config_files") != ",".join(self.files)
                or labels.get("com.docker.compose.config-hash") != hashes[service]
            ):
                raise UpdateError(
                    f"Configured baseline for {service} differs from the running container"
                )

    def stop_writers(self):
        self.call("close HTTPS ingress", "stop", "edge")
        self.call("stop API and scheduled backups", "stop", "api", "backup")

    def backup(self):
        # Scheduled backups are stopped so the exact dump and archive remain stable.
        name = self.call(
            "make and verify database and photo backup",
            "run",
            "-T",
            "--rm",
            "--no-deps",
            "--pull",
            "never",
            "backup",
            "python",
            "-c",
            BACKUP,
            timeout=3600,
        ).splitlines()[-1:]
        if not name or not re.fullmatch(r"regsys-\d{8}-\d{6}\.dump", name[0]):
            raise UpdateError("New verified backup was not reported")
        print(f"Verified backup: {name[0]}", flush=True)
        return name[0]

    def restart(self):
        self.stop_writers()
        self.call("remove stopped application containers", "rm", "-f", "edge", "api", "backup")
        # Reserve Caddy's static address before the API gets a dynamic address.
        for service in ("edge", "api", "backup"):
            self.call(
                f"start {service}",
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "120",
                service,
            )

    def health(self, config):
        host = config["services"]["edge"]["environment"]["RS_PUBLIC_HOST"]
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", host):
            raise UpdateError("Expected a DNS hostname for production HTTPS")
        opener = build_opener(NoRedirect())
        try:
            with opener.open(f"https://{host}/health", timeout=15) as response:
                health = json.loads(response.read(16384))
            with opener.open(f"https://{host}/", timeout=15) as response:
                if response.headers.get_content_type() != "text/html" or not response.read(1):
                    raise UpdateError("Production HTTPS endpoint did not serve the client")
        except (OSError, ValueError) as error:
            raise UpdateError("Production HTTPS health check failed") from error
        if health != {"status": "ok", "db": "ok"}:
            raise UpdateError("Production API or database is unhealthy")


def prepare(current, candidate, tag, directory):
    old = current.config()
    new = candidate.config()
    for key in ("volumes", "networks"):
        if old[key] != new[key]:
            raise UpdateError(f"Manual deployment required: Compose {key} changed")
    if old["services"]["db"] != new["services"]["db"]:
        raise UpdateError("Manual deployment required: database service configuration changed")
    for name in SERVICES:
        old_volumes = [
            mount for mount in old["services"][name].get("volumes", []) if mount["type"] == "volume"
        ]
        new_volumes = [
            mount for mount in new["services"][name].get("volumes", []) if mount["type"] == "volume"
        ]
        if old_volumes != new_volumes:
            raise UpdateError(f"Manual deployment required: persistent mounts for {name} changed")
    for name, keys in (
        ("api", ("RS_SECRET_KEY", "RS_DATABASE_URL", "RS_PUBLIC_BASE_URL")),
        ("edge", ("RS_PUBLIC_HOST", "RS_TLS_ISSUER")),
    ):
        for key in keys:
            if old["services"][name]["environment"].get(key) != new["services"][name][
                "environment"
            ].get(key):
                raise UpdateError(f"Manual deployment required: production setting {key} changed")
    current.verify_baseline(old)
    current.health(old)
    expected = current.revisions()
    old_heads = current.call(
        "read current image revisions", "exec", "-T", "api", "python", "-c", HEADS
    )
    if not expected or set(old_heads.splitlines()) != expected:
        raise UpdateError("Manual deployment required: deployed API and database revisions differ")
    images = directory / "images.tar"
    verify_image_tags(images, tag)
    check_image_disk_space(images)
    run(
        "load server release images", "docker", "image", "load", "--input", str(images), timeout=900
    )
    for service, image in image_names(tag).items():
        if new["services"][service].get("image") != image:
            raise UpdateError(f"Unexpected candidate image for {service}")
    new_heads = run(
        "read candidate image revisions",
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        image_names(tag)["api"],
        "python",
        "-c",
        HEADS,
    )
    if set(new_heads.splitlines()) != expected:
        raise UpdateError("Manual deployment required: candidate needs a database migration")
    validate_edge(new["services"]["edge"], image_names(tag)["edge"])


def check_image_disk_space(images):
    data_root = run("locate Docker storage", "docker", "info", "--format", "{{.DockerRootDir}}")
    if (
        not data_root
        or shutil.disk_usage(data_root).free < images.stat().st_size * 2 + DISK_RESERVE
    ):
        raise UpdateError("Insufficient Docker storage for loading server images")


def validate_edge(edge, image):
    command = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--entrypoint",
        "caddy",
    ]
    for key in ("RS_PUBLIC_HOST", "RS_TLS_ISSUER"):
        command += ["--env", f"{key}={edge['environment'][key]}"]
    for mount in edge.get("volumes", []):
        if mount["type"] == "bind":
            command += [
                "--mount",
                f"type=bind,src={mount['source']},dst={mount['target']},readonly",
            ]
    run(
        "validate Caddy without production networking",
        *command,
        image,
        "validate",
        "--config",
        "/etc/caddy/Caddyfile",
    )
