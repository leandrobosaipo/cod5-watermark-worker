#!/bin/bash

set -e

echo "==> Applying .env (if present)"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "==> Starting queue (Celery) if QUEUE_BACKEND is set and starts with redis://"

if [[ "${QUEUE_BACKEND}" == redis://* ]]; then
  celery -A app.core.queue worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2} &
else
  echo "==> QUEUE_BACKEND not set to Redis. Using in-process fallback."
fi

echo "==> Starting API (Uvicorn)"

uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-5344}

