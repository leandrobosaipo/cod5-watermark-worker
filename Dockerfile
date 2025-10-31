FROM python:3.10-slim

# Sistema
RUN apt-get update && apt-get install -y ffmpeg git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Python
RUN pip install --upgrade pip setuptools wheel

# Instala dependências principais primeiro (sem ultralytics)
RUN pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.0 torch==2.4.0 torchvision==0.19.0

# Instala o resto das dependências (sem ultralytics ainda)
# Vamos instalar ultralytics separadamente testando múltiplas versões
RUN pip install --no-cache-dir -r requirements.txt || \
    (echo "⚠ Instalação parcial de requirements.txt (sem ultralytics)" && \
     pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.0 torch==2.4.0 torchvision==0.19.0 \
     opencv-python==4.10.0.84 numpy==1.26.4 pillow==10.4.0 ffmpeg-python==0.2.0 \
     requests==2.32.3 tqdm==4.66.5 boto3==1.35.20 botocore==1.35.20 \
     python-multipart==0.0.9 celery==5.4.0 redis==5.1.0 pydantic-settings==2.5.2)

# YOLO weights (baixado antes para permitir teste completo de compatibilidade)
RUN mkdir -p models && \
    curl -L -o models/best.pt "https://github.com/linkedlist771/SoraWatermarkCleaner/releases/download/V0.0.1/best.pt"

# Instala ultralytics testando múltiplas versões até encontrar uma compatível
# Ordem de teste: mais recentes primeiro, depois versões mais antigas
# Versões 8.0.x mais recentes podem ter estrutura diferente mas ainda funcionar
# Agora que o modelo está disponível, o check_c3k2.py pode testar carregamento completo
RUN python3 check_c3k2.py && echo "✓ Compatibilidade verificada com ultralytics do requirements.txt" || \
    (echo "⚠ Testando versões alternativas do ultralytics..." && \
     (echo "→ Tentando 8.0.196..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==8.0.196 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==8.0.196" || \
     (echo "→ Tentando 8.1.0..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==8.1.0 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==8.1.0" || \
     (echo "→ Tentando 8.0.100..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==8.0.100 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==8.0.100" || \
     (echo "→ Tentando 8.0.20..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==8.0.20 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==8.0.20" || \
     (echo "→ Tentando 8.0.0..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==8.0.0 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==8.0.0" || \
     (echo "→ Tentando 7.1.0 (série 7.x)..." && \
      pip install --no-cache-dir --force-reinstall ultralytics==7.1.0 && \
      python3 check_c3k2.py && echo "✓ Compatível com ultralytics==7.1.0" || \
     (echo "✗ Nenhuma versão testada é compatível!" && \
      echo "Versões testadas: 8.0.196, 8.1.0, 8.0.100, 8.0.20, 8.0.0, 7.1.0" && \
      echo "WARNING: O modelo best.pt pode precisar ser reexportado" && \
      echo "OU pode ser necessário usar uma versão customizada do ultralytics" && \
      exit 1))))))))

# Dirs padrão
RUN mkdir -p uploads outputs

EXPOSE 5344

CMD ["bash", "start.sh"]

