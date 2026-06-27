FROM python:3.13-alpine

LABEL org.opencontainers.image.source="https://github.com/mrkvka/frigate-telegram-bot"
LABEL org.opencontainers.image.description="Telegram bot for Frigate NVR with Telegram-safe video normalization"
LABEL org.opencontainers.image.licenses="MIT"

RUN apk add --no-cache ffmpeg

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ /app/bot/
COPY bot.py /app/bot.py

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import os,time,sys; age=time.time()-os.path.getmtime('/tmp/bot_alive'); sys.exit(0 if age<120 else 1)"

CMD ["python", "-m", "bot"]
