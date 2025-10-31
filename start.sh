#!/bin/bash

# Não usa set -e para capturar erros melhor
set +e

echo "==> COD5 Watermark Worker Starting..."
echo "==> Python version: $(python3 --version)"
echo "==> Working directory: $(pwd)"

echo "==> Applying .env (if present)"

if [ -f .env ]; then
  set -a
  source .env
  set +a
  echo "==> Environment variables loaded"
else
  echo "==> No .env file found, using system environment"
fi

echo "==> Checking queue backend configuration..."

if [[ "${QUEUE_BACKEND}" == redis://* ]]; then
  echo "==> Redis detected: ${QUEUE_BACKEND}"
  echo "==> Starting Celery worker in background..."
  
  # Verifica se celery está disponível
  if command -v celery &> /dev/null; then
    celery -A app.core.queue:celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2} &
    CELERY_PID=$!
    echo "==> Celery worker started with PID: $CELERY_PID"
    sleep 2
    # Verifica se o processo ainda está rodando
    if ! kill -0 $CELERY_PID 2>/dev/null; then
      echo "==> WARNING: Celery worker may have failed to start"
    fi
  else
    echo "==> ERROR: celery command not found, falling back to in-process"
  fi
else
  echo "==> QUEUE_BACKEND not set to Redis. Using in-process fallback."
  echo "==> Queue backend: ${QUEUE_BACKEND:-not configured}"
fi

echo "==> Starting API (Uvicorn) on port ${API_PORT:-5344}"

# Usa exec para que o uvicorn seja o processo principal
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-5344}

