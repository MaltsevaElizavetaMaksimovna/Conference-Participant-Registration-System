# Проверка печати на XP-360B

Коротко:

```powershell
chcp 65001                      # русский текст в консоли; запускайте в Windows Terminal / PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python print_spike.py test --dry-run      # без принтера: PNG и .prn в spike_out\
python print_spike.py list
```

Подкоманды: `list`, `status`, `test`, `two`, `raw`, `bench` (`--help` у каждой).
Лог каждого запуска дописывается в `spike_out\spike_log.txt`.
