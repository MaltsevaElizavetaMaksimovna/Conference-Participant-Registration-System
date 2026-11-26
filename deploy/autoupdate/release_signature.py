"""Sign and verify the release identity and archive digest with Ed25519."""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from release_bundle import version

SIGNATURE = "regsys-linux-amd64.sig"
SIGNATURE_SIZE = 64


def payload(repository, tag, digest):
    version(tag)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository, re.ASCII) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", digest
    ):
        raise ValueError("Invalid signed release identity")
    return f"regsys-release-v1\n{repository}\n{tag}\n{digest}\n".encode("ascii")


def openssl(operation, key, data, *args):
    with tempfile.TemporaryDirectory() as work:
        message = Path(work) / "release.txt"
        message.write_bytes(data)
        return subprocess.run(
            [
                "openssl",
                "pkeyutl",
                operation,
                "-rawin",
                "-inkey",
                str(key),
                "-in",
                str(message),
                *args,
            ],
            capture_output=True,
            timeout=15,
            check=False,
            env={
                key: value
                for key, value in os.environ.items()
                if key != "REGSYS_GITHUB_TOKEN" and not key.startswith("REGSYS_SMTP_")
            },
        )


def verify(key, data, signature):
    try:
        valid = (
            signature.stat().st_size == SIGNATURE_SIZE
            and openssl(
                "-verify", key, data, "-pubin", "-sigfile", str(signature)
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Cannot verify release signature") from error
    if not valid:
        raise ValueError("Release signature is invalid")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("tag")
    parser.add_argument("digest")
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--output", default=SIGNATURE, type=Path)
    args = parser.parse_args()
    data = payload(args.repository, args.tag, args.digest)
    result = openssl("-sign", args.key, data)
    if result.returncode or len(result.stdout) != SIGNATURE_SIZE:
        raise SystemExit("Could not sign release with the supplied Ed25519 key")
    with args.output.open("xb") as output:
        output.write(result.stdout)


if __name__ == "__main__":
    main()
