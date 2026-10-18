FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Сначала зависимости — слой кэшируется, пока не меняется pyproject.toml
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app

COPY . .

RUN useradd --system --create-home --uid 1000 app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
