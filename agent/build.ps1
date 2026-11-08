# Сборка исполняемого файла regsys-agent в один exe

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Создание виртуального окружения при отсутствии
if (-not (Test-Path ".venv")) {
    py -3.12 -m venv .venv
}

# Установка зависимостей и pyinstaller
& .venv\Scripts\pip install -e ".[dev]" pyinstaller

# Сборка одного консольного exe-файла
& .venv\Scripts\pyinstaller --onefile --name regsys-agent --console regsys_agent/__main__.py
