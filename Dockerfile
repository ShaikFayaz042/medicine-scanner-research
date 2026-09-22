FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY cloud_worker/requirements.txt ./requirements.scraper.txt

RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.scraper.txt

COPY cloud_worker ./cloud_worker

CMD ["python", "-m", "cloud_worker.scraper.main"]
