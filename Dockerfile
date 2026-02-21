FROM python:3.11-slim

WORKDIR /app

# System dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    playwright install chromium

# Copy application code
COPY server/ server/
COPY schemas/ schemas/

# Create data directory
RUN mkdir -p /app/data

ENV HERMES_DATA_DIR=/app/data
ENV HERMES_PORT=8080
ENV HERMES_LOG_LEVEL=INFO

EXPOSE 8080

CMD ["uvicorn", "server.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
