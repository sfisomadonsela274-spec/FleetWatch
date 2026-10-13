FROM node:20-bookworm-slim

# Install Python 3.12, Nginx, and Supervisord
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Setup Python Virtual Environment for FastAPI
COPY backend/requirements.txt ./backend/
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r ./backend/requirements.txt

# 2. Setup Node.js Dependencies
COPY package*.json ./
RUN npm ci --omit=dev

# 3. Copy Application Source Files
COPY server/ ./server/
COPY backend/ ./backend/
COPY index.html ./
COPY journey_data.js ./
COPY *.jpg ./
COPY mobile/ ./mobile/

# 4. Copy Production Nginx & Supervisor Configs
COPY nginx/nginx-fly.conf /etc/nginx/sites-available/default
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

ENV PATH="/opt/venv/bin:$PATH" \
    PORT=4000 \
    FASTAPI_URL=http://127.0.0.1:8001

# Koyeb public port
EXPOSE 8080

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
