"""Запуск для разработки: локальная БД + uvicorn с автоперезагрузкой.

    python scripts/run_dev.py [порт]

RS_DATABASE_URL, если задан, не перезаписывается (тогда БД не поднимается).
"""

import os
import sys

import dev_db  # лежит рядом: при запуске скрипта его папка первая в sys.path
import uvicorn

if __name__ == "__main__":
    if not os.environ.get("RS_DATABASE_URL"):
        os.environ["RS_DATABASE_URL"] = dev_db.start()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    # reload=True на Windows даёт SelectorEventLoop, который нужен psycopg async
    uvicorn.run("app.main:app", port=port, reload=True, reload_dirs=["app"])
