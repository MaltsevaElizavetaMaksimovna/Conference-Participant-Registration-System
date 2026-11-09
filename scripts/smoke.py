"""Read-only checks of the SPA, Caddy API proxy and database readiness."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


class SmokeError(Exception):
    pass


def _get(url: str, timeout: float) -> tuple[int, str, bytes]:
    try:
        response = urlopen(url, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        return (
            response.code,
            response.headers.get_content_type(),
            response.read(1_000_000),
        )


def check(base_url: str, timeout: float = 5) -> list[str]:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise SmokeError("Use an HTTP(S) base URL without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise SmokeError("Use the server origin without a path, query or fragment")
    origin = base_url.rstrip("/")
    passed = []
    for path in ("/health", "/", "/login", "/api/auth/me"):
        try:
            status, content_type, body = _get(origin + path, timeout)
            if path == "/health":
                data = json.loads(body)
                valid = (
                    status == 200
                    and content_type == "application/json"
                    and data == {"status": "ok", "db": "ok"}
                )
            elif path.startswith("/api/"):
                data = json.loads(body)
                valid = (
                    status == 401
                    and content_type == "application/json"
                    and data.get("code") == "unauthenticated"
                )
            else:
                valid = (
                    status == 200
                    and content_type == "text/html"
                    and b'id="root"' in body
                )
        except (OSError, URLError, ValueError, TypeError, AttributeError) as error:
            raise SmokeError(
                f"{path}: response unavailable or invalid ({type(error).__name__})"
            ) from error
        if not valid:
            raise SmokeError(
                f"{path}: unexpected response, HTTP {status}, type {content_type}"
            )
        passed.append(path)
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    try:
        for path in check(args.base_url):
            print(f"OK {path}")
    except SmokeError as error:
        parser.exit(1, f"Smoke failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
