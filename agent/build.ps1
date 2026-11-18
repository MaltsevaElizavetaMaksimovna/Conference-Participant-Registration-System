# Сборка исполняемого файла regsys-agent.
$ErrorActionPreference = 'Stop'

Push-Location -LiteralPath $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать виртуальное окружение' }
    }

    & $python -m pip install -e '.[dev]' pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости сборки' }

    & $python -m PyInstaller --noconfirm --onefile --name regsys-agent --console regsys_agent/__main__.py
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось собрать regsys-agent.exe' }

    $binary = Join-Path $PSScriptRoot 'dist\regsys-agent.exe'
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        throw 'Сборщик не создал regsys-agent.exe'
    }
    Get-Item -LiteralPath $binary
}
finally {
    Pop-Location
}
