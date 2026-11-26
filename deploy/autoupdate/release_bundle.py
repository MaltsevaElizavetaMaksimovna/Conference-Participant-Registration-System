"""Build and unpack the fixed set of files in a server release."""

import json
import re
import shutil
import sys
import tarfile
from io import BytesIO
from pathlib import Path

ASSET = "regsys-linux-amd64.tar.gz"
MAX_ASSET_SIZE = 2_000_000_000
MAX_EXTRACTED_SIZE = 8_000_000_000
DISK_RESERVE = 1_073_741_824
SERVICES = ("api", "backup", "edge")
OVERLAYS = ("docker-compose.backup-mirror.yml", "docker-compose.kiosk.yml")
COMPOSE_FILES = ("docker-compose.prod.yml", *OVERLAYS)
CONFIG_FILES = (*COMPOSE_FILES, "deploy/Caddyfile", "deploy/kiosk.caddy")
MEMBERS = (*CONFIG_FILES, "images.tar", "release.json", "release-images.json")


def version(tag):
    if not isinstance(tag, str) or not re.fullmatch(
        r"v(0|[1-9][0-9]{0,8})(\.(0|[1-9][0-9]{0,8})){2}", tag
    ):
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH tag")
    return tuple(map(int, tag[1:].split(".")))


def image_names(tag):
    version(tag)
    return {service: f"regsys/{service}:{tag}" for service in SERVICES}


def compose_override(tag):
    return {"services": {name: {"image": image} for name, image in image_names(tag).items()}}


def pack(source, images, metadata, destination):
    validate_metadata(metadata, metadata["version"])
    with tarfile.open(destination, "x:gz") as archive:
        for name in CONFIG_FILES:
            path = source / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"Missing regular release file {name}")
            archive.add(path, arcname=name, recursive=False)
        archive.add(images, arcname="images.tar", recursive=False)
        for name, value in (
            ("release.json", metadata),
            ("release-images.json", compose_override(metadata["version"])),
        ):
            payload = json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))
    if destination.stat().st_size > MAX_ASSET_SIZE:
        raise ValueError("Server release exceeds the configured download limit")


def validate_metadata(metadata, tag):
    version(tag)
    if (
        metadata["version"] != tag
        or metadata["platform"] != "linux/amd64"
        or not re.fullmatch(r"[0-9a-f]{40}", metadata["commit"])
    ):
        raise ValueError("Release version, platform or source commit is invalid")


def unpack(archive_path, directory, tag):
    seen = set()
    total = 0
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            total += member.size
            limit = MAX_EXTRACTED_SIZE if member.name == "images.tar" else 1_000_000
            if (
                member.name not in MEMBERS
                or member.name in seen
                or not member.isfile()
                or not 0 < member.size <= limit
                or total > MAX_EXTRACTED_SIZE
            ):
                raise ValueError("Unexpected or oversized server release member")
            seen.add(member.name)
            target = directory / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(target.parent).free < member.size + DISK_RESERVE:
                raise ValueError("Insufficient space to extract the server release")
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    if seen != set(MEMBERS):
        raise ValueError("Incomplete server release")
    validate_metadata(json.loads((directory / "release.json").read_text()), tag)
    if json.loads((directory / "release-images.json").read_text()) != compose_override(tag):
        raise ValueError("Unexpected release image names")


def verify_image_tags(path, tag):
    with tarfile.open(path, "r:") as archive:
        member = archive.getmember("manifest.json")
        if not member.isfile() or not 0 < member.size <= 1_000_000:
            raise ValueError("Invalid Docker image manifest")
        with archive.extractfile(member) as source:
            manifest = json.load(source)
    tags = sorted(image for entry in manifest for image in entry["RepoTags"])
    if tags != sorted(image_names(tag).values()):
        raise ValueError("Docker archive contains unexpected image tags")


if __name__ == "__main__":
    tag, commit, images_arg, output_arg = sys.argv[1:]
    pack(
        Path.cwd(),
        Path(images_arg),
        {"version": tag, "commit": commit, "platform": "linux/amd64"},
        Path(output_arg),
    )
