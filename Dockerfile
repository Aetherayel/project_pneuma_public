FROM python:3.12-slim

# Wake-on-LAN utility + CA certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    wakeonlan \
    ca-certificates \
    ffmpeg \
    nodejs \
    docker.io \
    docker-compose \
  && rm -rf /var/lib/apt/lists/*

# --- Deno runtime for yt-dlp EJS challenge solving ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | sh
RUN ln -sf /root/.deno/bin/deno /usr/local/bin/deno
ENV DENO_INSTALL=/root/.deno
ENV PATH=$DENO_INSTALL/bin:$PATH

# yt-dlp
RUN pip install --no-cache-dir -U yt-dlp

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/
COPY index_runtime.py /app/
COPY templates /app/templates
COPY static /app/static

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
