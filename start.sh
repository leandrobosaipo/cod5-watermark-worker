#!/bin/bash

# Não usa set -e para capturar erros melhor
set +e

echo "==> COD5 Watermark Worker Starting..."
echo "==> Python version: $(python3 --version)"
echo "==> Working directory: $(pwd)"

# Validação crítica: verifica versão do ultralytics
echo "==> Validating ultralytics version..."
ULTRALYTICS_VERSION=$(python3 -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$ULTRALYTICS_VERSION" ]; then
    echo "==> ERROR: Failed to import ultralytics"
    exit 1
fi

echo "==> Ultralytics version: $ULTRALYTICS_VERSION"

# Verifica se C3k2 está disponível (mais importante que a versão exata)
C3K2_AVAILABLE=$(python3 -c "from ultralytics.nn.modules.block import C3k2; print('OK')" 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$C3K2_AVAILABLE" ]; then
    echo "==> ERROR: C3k2 module not found in ultralytics!"
    echo "==> Version: $ULTRALYTICS_VERSION"
    echo "==> This model requires a version with C3k2 module."
    echo "==> Trying alternative versions..."
    
    # Tenta versões alternativas
    for version in "8.0.100" "8.0.20" "8.0.10"; do
        echo "==> Attempting ultralytics==$version..."
        pip install --no-cache-dir --force-reinstall ultralytics==$version
        if python3 -c "from ultralytics.nn.modules.block import C3k2" 2>/dev/null; then
            echo "==> ✓ Found C3k2 with ultralytics==$version"
            ULTRALYTICS_VERSION=$(python3 -c "import ultralytics; print(ultralytics.__version__)")
            break
        fi
    done
    
    # Verifica novamente
    if ! python3 -c "from ultralytics.nn.modules.block import C3k2" 2>/dev/null; then
        echo "==> ERROR: Could not find C3k2 in any tested version!"
        exit 1
    fi
fi

echo "==> ✓ Ultralytics version OK"

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

