# Worker Dockerfile for PCC Platform
# Multi-stage build for AI processing and background tasks

# =====================================================
# Stage 1: Build dependencies
# =====================================================
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /app

# Install system dependencies required for Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY worker/requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# =====================================================
# Stage 2: Runtime image
# =====================================================
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN addgroup --system app && adduser --system --group app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \  # For audio processing (transcription)
    poppler-utils \  # For PDF processing
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder stage
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

# Install dependencies
RUN pip install --no-cache /wheels/*

# Copy application code
COPY worker/ .

# Set environment variables
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0 \
    WORKERS=2 \
    CELERY_BROKER_URL="memory://" \  # Default in-memory broker, override in production
    CELERY_RESULT_BACKEND="memory://" \  # Default in-memory backend, override in production
    CONCURRENCY=2 \  # Celery worker concurrency
    MAX_TASKS_PER_CHILD=100  # Restart worker after processing this many tasks

# Build arguments
ARG APP_ENV=production
ENV APP_ENV=${APP_ENV}

# Switch to non-root user
USER app

# Health check - worker exposes a health endpoint for Cloud Run autoscaler
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# Expose port for health checks and API
EXPOSE ${PORT}

# Create startup script to run either API or Celery worker based on WORKER_MODE env var
RUN echo '#!/bin/bash\n\
if [ "$WORKER_MODE" = "api" ]; then\n\
  echo "Starting worker API mode..."\n\
  exec uvicorn app.main:app --host ${HOST} --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips="*"\n\
else\n\
  echo "Starting Celery worker mode..."\n\
  exec celery -A app.worker.celery_app worker --loglevel=info --concurrency=${CONCURRENCY} --max-tasks-per-child=${MAX_TASKS_PER_CHILD}\n\
fi' > /app/start.sh && chmod +x /app/start.sh

# Default to API mode for Cloud Run compatibility
ENV WORKER_MODE=api

# Run the startup script
CMD ["/app/start.sh"]
