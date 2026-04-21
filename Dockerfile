FROM python:3.13-alpine

LABEL org.opencontainers.image.source="https://github.com/mrkvka/frigate-telegram-bot"
LABEL org.opencontainers.image.description="Telegram bot for Frigate NVR: /status /snapshot /last"
LABEL org.opencontainers.image.licenses="MIT"

RUN pip install --no-cache-dir requests==2.32.3

WORKDIR /app
COPY bot.py /app/bot.py

ENV PYTHONUNBUFFERED=1 \
    FRIGATE_URL=http://frigate:5000 \
    POLL_TIMEOUT=30 \
    CAMERA=front \
    MAX_VIDEO_MB=45

HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import requests; requests.get('https://api.telegram.org', timeout=5)" || exit 1

CMD ["python", "/app/bot.py"]
