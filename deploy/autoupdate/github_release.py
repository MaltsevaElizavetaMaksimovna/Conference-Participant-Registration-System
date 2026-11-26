"""Read releases and download the verified asset without forwarding credentials."""

import hashlib
import json
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from release_bundle import ASSET, MAX_ASSET_SIZE, version


class GitHubRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        host = url.hostname or ""
        if url.scheme != "https" or not (
            host in ("api.github.com", "github.com") or host.endswith(".githubusercontent.com")
        ):
            raise ValueError("Unexpected release download host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubRelease:
    def __init__(self, repository, token=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository, re.ASCII):
            raise ValueError("Invalid release repository")
        self.base = f"https://api.github.com/repos/{repository}/releases"
        self.token = token
        self.opener = build_opener(GitHubRedirect())

    def request(self, endpoint, accept):
        request = Request(self.base + endpoint, headers={"Accept": accept})
        if self.token:
            request.add_unredirected_header("Authorization", f"Bearer {self.token}")
        return self.opener.open(request, timeout=30)

    def latest(self, installed, blocked):
        with self.request("/latest", "application/vnd.github+json") as response:
            release = json.loads(response.read(1_000_000))
        if release["draft"] or release["prerelease"]:
            return None
        tag = release["tag_name"]
        try:
            if version(tag) <= version(installed) or tag == blocked:
                return None
        except ValueError:
            return None
        assets = [asset for asset in release["assets"] if asset["name"] == ASSET]
        if not assets:
            return None
        if len(assets) != 1:
            raise ValueError("Expected exactly one server release asset")
        asset = assets[0]
        if (
            type(asset["id"]) is not int
            or asset["id"] <= 0
            or asset["state"] != "uploaded"
            or type(asset["size"]) is not int
            or not 0 < asset["size"] <= MAX_ASSET_SIZE
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or "")
        ):
            raise ValueError("Invalid release asset metadata")
        return tag, asset

    def download(self, asset, target):
        digest = hashlib.sha256()
        received = 0
        with (
            self.request(f"/assets/{asset['id']}", "application/octet-stream") as response,
            target.open("xb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > asset["size"]:
                    raise ValueError("Release download exceeded its declared size")
                digest.update(chunk)
                output.write(chunk)
        if received != asset["size"] or f"sha256:{digest.hexdigest()}" != asset["digest"]:
            raise ValueError("Release download failed its SHA-256 or size check")
