FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
COPY web ./web
RUN useradd -u 10001 -m mada && mkdir -p /data /downloads && chown -R mada:mada /data /downloads
USER mada
ENV MADA_DATA_DIR=/data MADA_DOWNLOAD_DIR=/downloads PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
