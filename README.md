# Бэкенд системы регистрации участников конференции

Участник сканирует QR-код на терминале, подтверждает данные, принтер печатает наклейку на бейдж.
Здесь серверная часть (API, база данных) и программа печати для терминалов.

## Стек

Python 3.12, FastAPI, SQLAlchemy 2 (async, psycopg 3), PostgreSQL 16, Alembic, pytest.
Печать — на Xprinter XP-360B (TSPL).

## Структура

```
backend/
  app/          приложение FastAPI (модули по предметным областям)
  migrations/   миграции Alembic
  scripts/      запуск локальной БД и сервера
  tests/        автотесты
agent/          печать наклеек на терминале
scripts/        общая проверка проекта
```

## Запуск (Windows, без Docker)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/dev_db.py            # локальный PostgreSQL, печатает DATABASE_URL
$env:RS_DATABASE_URL = "<URL из вывода>"
python -m app.cli migrate
uvicorn app.main:app --loop app.core.loop:selector_loop_factory --reload
```

Документация API — http://127.0.0.1:8000/docs.

С Docker: `docker compose up`.

## Резервное копирование

Из каталога `backend`. Запустить перед началом регистрации: первая копия сразу, затем каждые 30 мин
(`RS_BACKUP_INTERVAL_MIN`), файлы в `backend/.data/backups`; копия на второй носитель —
`RS_BACKUP_MIRROR_DIR`. В копиях персональные данные: хранить так же, как саму БД.
```bash
python scripts/backup.py loop
```
Проверка пригодности последнего дампа:
```bash
python scripts/backup.py verify
```
Ручное восстановление базы и фото:
```bash
pg_restore --clean --if-exists --no-owner -d <БД> <файл>.dump
# распаковать архив фото в RS_PHOTO_DIR
```

## Проверка

```bash
bash scripts/verify.sh      # ruff, mypy, pytest
```

Тесты сами поднимают временный PostgreSQL, отдельная база не нужна.

# Фронтэнд системы регистрации участников конференции

## Стек

    React, Redux Toolkit, Typescript, React Router, Axios, React QR Scanner.

## Структура

```
client/src
  api/          конфигурация Axios
  assets/   
  components/    
  config/        константы
  hooks/        хуки для redux
  models/        модели данных
  modules/        модули приложения
  pages/        страницы приложения
  services/        сервисы для взаимодействия с API
  store/        хранилище redux
  styles/        стили
  utils/        утилиты
  main.tsx      стартовая точка приложения с роутингом
```

## Запуск
1. Убедитесь, что у вас установлен Node.js (версия 18 или выше).
2. Установите зависимости:
    ``` 
   npm install
   ```
3. Запустите dev-сервер:
    ```
   npm start
   ```
