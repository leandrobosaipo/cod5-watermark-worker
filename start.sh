#!/bin/bash

# Não usa set -e para capturar erros melhor
set +e

echo "================================================================================"
echo "🚀 COD5 WATERMARK WORKER - Iniciando..."
echo "================================================================================"
echo "[INFO] Python version: $(python3 --version)"
echo "[INFO] Working directory: $(pwd)"
echo ""

# Validação crítica: verifica versão do ultralytics
echo "[CHECK] Validando versão do Ultralytics..."
ULTRALYTICS_VERSION=$(python3 -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$ULTRALYTICS_VERSION" ]; then
    echo "[ERROR] ❌ Falha ao importar ultralytics"
    exit 1
fi

echo "[INFO] ✅ Ultralytics instalado | Versão: $ULTRALYTICS_VERSION"

# Verifica compatibilidade do ultralytics usando o script de verificação
# Este script testa múltiplas estratégias e tenta carregar o modelo se disponível
echo "[CHECK] Verificando compatibilidade do Ultralytics com modelo YOLO..."
if python3 check_c3k2.py 2>/dev/null; then
    echo "[INFO] ✅ Ultralytics compatível com modelo YOLO"
else
    echo "[WARN] ⚠ Aviso: Verificação de compatibilidade falhou"
    echo "[INFO] Tentando versões alternativas do Ultralytics..."
    
    # Tenta versões alternativas (fallback durante runtime)
    for version in "8.0.196" "8.1.0" "8.0.100" "8.0.20" "8.0.0"; do
        echo "[INFO]   → Tentando ultralytics==$version..."
        pip install --no-cache-dir --force-reinstall ultralytics==$version 2>/dev/null
        if python3 check_c3k2.py 2>/dev/null; then
            echo "[INFO] ✅ Compatível com ultralytics==$version"
            ULTRALYTICS_VERSION=$(python3 -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null)
            break
        fi
    done
    
    # Verificação final
    if ! python3 check_c3k2.py 2>/dev/null; then
        echo "[WARN] ⚠ Não foi possível verificar compatibilidade completamente"
        echo "[WARN] A aplicação tentará carregar o modelo na inicialização"
        echo "[WARN] Se houver erro de C3k2, será reportado durante o uso do modelo"
    fi
fi

echo "[INFO] Versão final do Ultralytics: ${ULTRALYTICS_VERSION:-$(python3 -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null || echo 'unknown')}"
echo ""

echo "[CONFIG] Carregando variáveis de ambiente..."
if [ -f .env ]; then
  set -a
  source .env
  set +a
  echo "[INFO] ✅ Variáveis de ambiente carregadas do arquivo .env"
else
  echo "[INFO] ⚠ Arquivo .env não encontrado | Usando variáveis do sistema"
fi
echo ""

echo "[CONFIG] Verificando configuração do backend de fila..."

if [[ "${QUEUE_BACKEND}" == redis://* ]]; then
  echo "[INFO] Redis detectado: ${QUEUE_BACKEND}"
  
  # Valida conexão com Redis antes de iniciar Celery
  echo "[CHECK] Validando conexão com Redis..."
  if python3 -c "import redis; r = redis.from_url('${QUEUE_BACKEND}', socket_connect_timeout=5); r.ping(); print('OK')" 2>/dev/null; then
    echo "[INFO] ✅ Conexão com Redis validada"
  else
    echo "[WARN] ⚠ Não foi possível conectar ao Redis"
    echo "[WARN] Celery não será iniciado, usando fallback ThreadPool"
    echo "[WARN] Verifique QUEUE_BACKEND ou remova para usar fallback"
    QUEUE_BACKEND=""
  fi
  
  if [[ "${QUEUE_BACKEND}" == redis://* ]]; then
    echo "[INFO] Iniciando worker Celery em background..."
    
    # Verifica se celery está disponível
    if command -v celery &> /dev/null; then
      celery -A app.core.queue:celery_app worker --loglevel=info --concurrency=${CELERY_CONCURRENCY:-2} &
      CELERY_PID=$!
      echo "[INFO] Celery worker iniciado | PID: $CELERY_PID"
      
      # Aguarda um pouco e verifica se ainda está rodando
      sleep 3
      if kill -0 $CELERY_PID 2>/dev/null; then
        echo "[INFO] ✅ Celery worker está rodando | PID: $CELERY_PID | Concurrency: ${CELERY_CONCURRENCY:-2}"
      else
        echo "[WARN] ⚠ Celery worker pode ter falhado ao iniciar"
        echo "[WARN] Aplicação continuará com fallback ThreadPool"
      fi
    else
      echo "[WARN] ⚠ Comando celery não encontrado | Usando fallback ThreadPool"
    fi
  fi
else
  echo "[INFO] QUEUE_BACKEND não configurado para Redis | Usando ThreadPool (fallback)"
  echo "[INFO] Queue backend: ${QUEUE_BACKEND:-not configured}"
fi
echo ""

echo "================================================================================"
echo "[INFO] 🚀 Iniciando API FastAPI (Uvicorn) na porta ${API_PORT:-5344}..."
echo "================================================================================"

# Usa exec para que o uvicorn seja o processo principal
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-5344}

