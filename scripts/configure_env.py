"""Create a local Compose .env without overwriting existing credentials."""

import argparse
import os
import secrets
from pathlib import Path


def create_env(path: Path) -> None:
    password = secrets.token_hex(24)
    secret = secrets.token_hex(32)
    content = (
        "# Local development only. Never commit this file.\n"
        f"POSTGRES_PASSWORD={password}\n"
        f"RS_SECRET_KEY={secret}\n"
        "RS_ENV=dev\nHTTP_BIND=127.0.0.1\nHTTP_PORT=8080\n"
        "API_BIND=127.0.0.1\nAPI_PORT=8000\n"
        "RS_PUBLIC_BASE_URL=http://localhost:8080\n"
        "RS_CORS_ORIGINS=http://localhost:8080,http://localhost:5173\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / ".env"
    )
    args = parser.parse_args()
    try:
        create_env(args.output)
    except FileExistsError:
        print(f"Existing file kept: {args.output}")
        return 0
    except OSError as error:
        parser.exit(1, f"Cannot create environment file: {error}\n")
    print(f"Created {args.output}. Credentials were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
