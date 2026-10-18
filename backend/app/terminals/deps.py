"""Текущий терминал и агент печати — общий интерфейс.

В тестах подменяются через `app.dependency_overrides[get_current_terminal]` / `[get_current_agent]`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentTerminal:
    terminal_id: int
    name: str
    printer_id: int | None


@dataclass(frozen=True)
class CurrentAgent:
    printer_id: int
    name: str


async def get_current_terminal() -> CurrentTerminal:
    """TODO B2-01: `Authorization: Terminal <token>` → терминал; 401, 423 terminal_disabled."""
    return CurrentTerminal(terminal_id=0, name="Терминал-заглушка", printer_id=None)


async def get_current_agent() -> CurrentAgent:
    """TODO B2-01: `Authorization: Agent <token>` → принтер; 401 при неверном токене."""
    return CurrentAgent(printer_id=0, name="Принтер-заглушка")
