# Агент печати regsys-agent

Агент печати наклеек участников для принтера XP-360B (B2-12, NF-03).
Получает задания с сервера по long-polling и отправляет их в спулер Windows.

## Настройка
1. Скопируйте `agent.example.ini` в `agent.ini`.
2. Укажите токен из админки принтеров в `RS_AGENT_TOKEN` или в параметре `token` в `agent.ini`.
3. Укажите имя принтера в системе (`printer_name`) и адрес сервера (`server_url`).

## Подключение принтера
Порядок включения принтера: сначала питание, потом USB (если включить с подключенным USB, переподключите кабель).

## Запуск
```powershell
python -m regsys_agent --config agent.ini
```

## Сборка
```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```
Результат сборки: `dist/regsys-agent.exe`.
