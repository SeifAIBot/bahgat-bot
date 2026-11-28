FROM python:3.12-slim

# ffmpeg converts Edge TTS mp3 -> ogg/opus voice notes.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV BAHGAT_DATA_DIR=/app/data
CMD ["python", "main.py"]
