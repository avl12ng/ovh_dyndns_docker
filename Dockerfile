# Small, portable image based on the official slim Python runtime.
FROM python:3.12-slim

# Do not buffer stdout/stderr so logs appear immediately in `docker logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app/ ./app/

# Run as a non-root user for better security.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Default command: run the updater once, then exit (one-shot mode).
ENTRYPOINT ["python", "-u", "app/update_dns.py"]
