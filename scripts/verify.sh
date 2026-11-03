#!/usr/bin/env bash
# Полная проверка проекта: линтер, типы, тесты бэкенда.
# Запуск из любой папки: bash scripts/verify.sh   (тесты сами поднимают встроенный PostgreSQL)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [ -f .venv/Scripts/activate ]; then . .venv/Scripts/activate
elif [ -f .venv/bin/activate ]; then . .venv/bin/activate
else echo "Нет backend/.venv: py -3.12 -m venv .venv && pip install -e \".[dev]\"" >&2; exit 1
fi

step() { echo "== $1"; }

step "ruff check";        ruff check . -q
step "ruff format";       ruff format --check -q .
step "mypy";              mypy app | tail -1
step "pytest";            pytest -q -p no:cacheprovider 2>&1 | tail -3


echo "== OK"
