FROM python:3.10-slim

# Sistema
RUN apt-get update && apt-get install -y ffmpeg git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Python
RUN pip install --upgrade pip setuptools wheel

RUN pip install -r requirements.txt

# YOLO weights
RUN mkdir -p models && \
    curl -L -o models/best.pt "https://github.com/linkedlist771/SoraWatermarkCleaner/releases/download/V0.0.1/best.pt"

# Dirs padrão
RUN mkdir -p uploads outputs

EXPOSE 5344

CMD ["bash", "start.sh"]

