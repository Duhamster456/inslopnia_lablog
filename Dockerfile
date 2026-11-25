FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 lablog \
    && useradd --uid 10001 --gid lablog --no-create-home lablog \
    && install -d -m 0700 -o lablog -g lablog /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lablog ./lablog

USER lablog
EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--preload", "--workers=2", "--threads=2", "lablog:create_app()"]
