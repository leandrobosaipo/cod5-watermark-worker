FROM python:3.10-slim

# Sistema
RUN apt-get update && apt-get install -y ffmpeg git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Python
RUN pip install --upgrade pip setuptools wheel

# Instala dependências principais primeiro (sem ultralytics)
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.0 torch==2.4.0 torchvision==0.19.0

# Instala ultralytics com versão fixada ANTES do requirements.txt para garantir
RUN pip install --no-cache-dir --force-reinstall ultralytics==8.0.196

# Instala o resto das dependências
# NOTA: requirements.txt tem ultralytics==8.0.196, mas vamos garantir que não seja atualizado
RUN pip install --no-cache-dir -r requirements.txt

# FORÇA a versão correta após instalar requirements (evita upgrades acidentais)
RUN pip install --no-cache-dir --force-reinstall --no-deps ultralytics==8.0.196

# Verifica versão instalada do ultralytics
RUN python3 -c "import ultralytics; print('Ultralytics version:', ultralytics.__version__); assert ultralytics.__version__.startswith('8.0.196'), f'Versão incorreta: {ultralytics.__version__}'" || exit 1

# YOLO weights
RUN mkdir -p models && \
    curl -L -o models/best.pt "https://github.com/linkedlist771/SoraWatermarkCleaner/releases/download/V0.0.1/best.pt"

# Dirs padrão
RUN mkdir -p uploads outputs

EXPOSE 5344

CMD ["bash", "start.sh"]

