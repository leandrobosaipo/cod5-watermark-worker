FROM python:3.10-slim

# ============================================
# ETAPA 1: Sistema - Layer cached separadamente
# ============================================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================
# ETAPA 2: Python setup - Layer cached
# ============================================
RUN pip install --upgrade pip setuptools wheel

# ============================================
# ETAPA 3: Dependências estáveis (cache otimizado)
# Copia requirements primeiro para melhor cache
# ============================================
COPY requirements.txt .
COPY check_c3k2.py .

# Instala dependências estáveis primeiro (mudam pouco) - melhor cache
# Essas dependências mudam raramente, então layer será cacheada
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn==0.30.0 \
    torch==2.4.0 \
    torchvision==0.19.0 \
    opencv-python==4.10.0.84 \
    numpy==1.26.4 \
    pillow==10.4.0 \
    ffmpeg-python==0.2.0 \
    requests==2.32.3 \
    tqdm==4.66.5 \
    boto3==1.35.20 \
    botocore==1.35.20 \
    python-multipart==0.0.9 \
    celery==5.4.0 \
    redis==5.1.0 \
    pydantic-settings==2.5.2 \
    aiofiles>=23.2.0

# ============================================
# ETAPA 4: YOLO weights - Layer separada com cache
# ============================================
RUN mkdir -p models && \
    echo "📥 Baixando modelo YOLO..." && \
    curl -L --progress-bar -o models/best.pt \
        "https://github.com/linkedlist771/SoraWatermarkCleaner/releases/download/V0.0.1/best.pt" && \
    echo "✅ Modelo baixado"

# ============================================
# ETAPA 5: Ultralytics - Otimizado com timing
# Testa versões em ordem de probabilidade de sucesso
# Usa script separado para evitar problemas de parsing
# ============================================
COPY install_ultralytics.sh .
RUN chmod +x install_ultralytics.sh && ./install_ultralytics.sh

# ============================================
# ETAPA 6: Código da aplicação (layer final)
# Esta layer muda frequentemente e será reconstruída
# ============================================
COPY . .

# ============================================
# ETAPA 7: Setup final
# ============================================
RUN mkdir -p uploads outputs

EXPOSE 5344

CMD ["bash", "start.sh"]

