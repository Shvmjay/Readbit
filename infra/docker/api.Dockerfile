# Readbit API and worker image (same image; different command).
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PROMPTS_DIR=/app/prompts
WORKDIR /app/services/api
COPY services/api/pyproject.toml ./
# Install dependencies first (cached layer), then the application source.
RUN pip install --upgrade pip && python -c "import tomllib;print('\\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
    && pip install -r /tmp/req.txt
COPY services/api/ ./
COPY prompts/ /app/prompts/
RUN useradd --create-home --uid 10001 readbit && chown -R readbit /app
USER readbit
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers ${API_WORKERS:-2}"]

# Worker variant with OCR support (tesseract) for scanned PDFs.
FROM base AS worker
USER root
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/*
USER readbit
HEALTHCHECK NONE
CMD ["sh", "-c", "celery -A app.workers.celery_app worker -Q documents,summaries,questions,maintenance,default --concurrency ${WORKER_CONCURRENCY:-2} --loglevel INFO"]
