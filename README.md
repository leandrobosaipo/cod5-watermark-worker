# 🧾 COD5 Watermark Worker

API escalável (FastAPI, Python 3.10) para **remover marcas d'água de vídeos Sora2** com processamento assíncrono em fila, armazenamento no DigitalOcean Spaces e status detalhado por tarefa.

## 📋 Funcionalidades

- ✅ **Processamento em fila** (Celery + Redis ou fallback ThreadPool)
- ✅ **Armazenamento no DigitalOcean Spaces** (upload, output e links públicos)
- ✅ **Status detalhado** (etapa, % progresso, tempo, modelo, logs)
- ✅ **Endpoints completos** (upload, status, download, listagem, delete, health)
- ✅ **Dockerfile pronto** para EasyPanel
- ✅ **Configuração flexível** via variáveis de ambiente

## 🚀 Início Rápido

### 1) Rodar Localmente

```bash
# Clone o repositório
git clone https://github.com/leandrobosaipo/cod5-watermark-worker.git
cd cod5-watermark-worker

# Crie ambiente virtual
python3 -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate

# Instale dependências
pip install -r requirements.txt

# Configure variáveis de ambiente
cp .env.example .env
# Edite .env com suas chaves do DigitalOcean Spaces

# Inicie a API
uvicorn app.main:app --reload --port 5344
```

**Documentação interativa:** `http://localhost:5344/docs`

### 2) Deploy no GitHub

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/leandrobosaipo/cod5-watermark-worker.git
git push -u origin main
```

### 3) Deploy no EasyPanel (Dockerfile)

1. **Novo App → "Deploy from Dockerfile"**
2. Repositório: `https://github.com/leandrobosaipo/cod5-watermark-worker.git`
3. Porta exposta: **5344**
4. **Variáveis de ambiente** (copie do `.env.example`, edite com suas chaves):
   - `SPACES_KEY` e `SPACES_SECRET` (chaves do DigitalOcean Spaces)
   - `SPACES_BUCKET` (nome do bucket)
   - `SPACES_REGION` e `SPACES_ENDPOINT` (região e endpoint)
   - Outras configurações opcionais
5. Deploy → aguarde build → abra `https://SEU_DOMINIO/docs`

> **Redis (opcional recomendado):** Crie um serviço Redis no EasyPanel e use sua URL em `QUEUE_BACKEND`. Sem Redis, o worker usa **fallback** in-process (bom para dev, limitado em produção).

### 4) Integração n8n (HTTP Request)

#### Upload (`POST /submit_remove_task`)

- **Método:** `POST`
- **Body:** `Form-Data`
- **Campo:** `file` (binary)
- **URL:** `https://SEU_DOMINIO/submit_remove_task`

Campos opcionais no Form-Data:
- `override_conf` (float, 0.05-0.8)
- `override_mask_expand` (int, pixels)
- `override_frame_stride` (int, ≥1)
- `webhook_url` (string, URL para POST ao concluir/erro)

#### Status (`GET /get_results`)

- **URL:** `https://SEU_DOMINIO/get_results?task_id={{$json.task_id}}`

#### Download (`GET /download/{task_id}`)

- **URL:** `https://SEU_DOMINIO/download/{{$json.task_id}}`

## 📡 Endpoints

### `POST /submit_remove_task`

Recebe o vídeo, envia para Spaces (`uploads/`), cria `task_id`, enfileira processamento.

**Form-Data:**
- `file` (obrigatório) — vídeo `.mp4|.mov|.avi` (até `MAX_FILE_MB`)
- `override_conf` (opcional, 0.05–0.8)
- `override_mask_expand` (opcional, pixels)
- `override_frame_stride` (opcional, ≥1)
- `webhook_url` (opcional, POST ao concluir/erro)

**Resposta 200 (JSON):**
```json
{
  "task_id": "cod5_1730389012",
  "status": "queued",
  "message": "Video received. Processing will start soon.",
  "spaces_input": "https://<bucket>.<region>.digitaloceanspaces.com/uploads/cod5_1730389012.mp4"
}
```

### `GET /get_results`

Status detalhado de uma tarefa.

**Query:** `task_id` (obrigatório)

**Resposta 200 (JSON):**
```json
{
  "task_id": "cod5_1730389012",
  "status": "processing",
  "progress": 72,
  "stage": "inpainting frames",
  "model_used": "YOLOv11s + LAMA-big",
  "started_at": "2025-10-31T03:12:00Z",
  "updated_at": "2025-10-31T03:14:12Z",
  "duration_seconds": 132,
  "frames_total": 480,
  "frames_done": 346,
  "spaces_input": "https://.../uploads/cod5_1730389012.mp4",
  "spaces_output": null,
  "log_excerpt": "Frame 346/480 cleaned...",
  "params_effective": {
    "yolo_conf": 0.25,
    "yolo_iou": 0.45,
    "mask_expand": 18,
    "frame_stride": 1,
    "torch_device": "mps"
  }
}
```

Quando finaliza (`completed`): inclui `spaces_output` e `message: "Watermark removed successfully"`.

### `GET /download/{task_id}`

Redireciona para URL pública do vídeo processado no Spaces (302).

### `GET /tasks`

Lista resumida das tarefas recentes.

**Query:** `limit` (opcional, 1-100, default: 50)

**Resposta 200 (JSON):**
```json
[
  {
    "task_id": "cod5_1730389012",
    "status": "completed",
    "progress": 100,
    "updated_at": "2025-10-31T03:16:01Z"
  },
  {
    "task_id": "cod5_1730390020",
    "status": "processing",
    "progress": 46,
    "updated_at": "2025-10-31T03:20:22Z"
  }
]
```

### `DELETE /tasks/{task_id}`

Remove metadados locais **e** arquivos do Spaces (`uploads/` e `outputs/`).

**Resposta 200 (JSON):**
```json
{
  "message": "Tarefa cod5_1730389012 deletada com sucesso"
}
```

### `GET /healthz`

Health check com latência do Spaces e ping da fila.

**Resposta 200 (JSON):**
```json
{
  "ok": true,
  "redis": "up",
  "spaces": "up",
  "uptime_seconds": 1234
}
```

## 🧪 Exemplos `curl`

> Substitua `SEU_DOMINIO` e caminhos de arquivo.

### 1) Enviar vídeo

```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -H "Accept: application/json" \
  -F "file=@/caminho/para/video.mp4"
```

### 2) Enviar vídeo com overrides e webhook

```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -F "file=@/caminho/para/video.mp4" \
  -F "override_conf=0.2" \
  -F "override_mask_expand=24" \
  -F "override_frame_stride=1" \
  -F "webhook_url=https://webhook.site/SEU_ID"
```

### 3) Ver status

```bash
curl "https://SEU_DOMINIO/get_results?task_id=cod5_1730389012"
```

### 4) Listar tarefas

```bash
curl "https://SEU_DOMINIO/tasks"
```

### 5) Baixar resultado

```bash
curl -L -o output.mp4 "https://SEU_DOMINIO/download/cod5_1730389012"
```

### 6) Deletar tarefa

```bash
curl -X DELETE "https://SEU_DOMINIO/tasks/cod5_1730389012"
```

### 7) Health check

```bash
curl "https://SEU_DOMINIO/healthz"
```

## ⚙️ Configuração (`.env`)

```bash
# API
API_PORT=5344
CORS_ORIGINS=*

# Queue (use Redis para produção; vazio ativa fallback ThreadPool)
QUEUE_BACKEND=redis://redis:6379/0
CELERY_CONCURRENCY=2

# Spaces
SPACES_REGION=nyc3
SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
SPACES_BUCKET=cod5
SPACES_KEY=***COLOQUE_AQUI***
SPACES_SECRET=***COLOQUE_AQUI***

# Modelos & Device
YOLO_MODEL_PATH=/app/models/best.pt
TORCH_DEVICE=mps            # cpu|mps|cuda
YOLO_CONF=0.25              # 0.05–0.8
YOLO_IOU=0.45               # 0.1–0.9
MASK_EXPAND=18              # pixels
FRAME_STRIDE=1              # 1 = todos os frames

# Limites & housekeeping
MAX_FILE_MB=800
ALLOWED_MIME=video/mp4,video/quicktime,video/x-msvideo
TASK_TTL_HOURS=72
```

> **Segurança:** Nunca faça commit de `.env` com chaves reais. Use `.env.example`.

## 🧠 Pipeline de Processamento

1. **Recebimento:** Valida MIME/tamanho, salva no Spaces (`uploads/`), cria `task_id`.
2. **Fila:** Celery (Redis) ou fallback ThreadPool.
3. **Processamento:**
   - Extrai frames (FFmpeg).
   - **YOLO** detecta regiões (logo Sora e similares).
   - Expande/une máscaras (`MASK_EXPAND`).
   - **LAMA** faz inpainting nas áreas detectadas.
   - Render final (FFmpeg), mantém áudio.
4. **Publicação:** Envia para `outputs/` no Spaces, atualiza status 100%.
5. **Webhook (opcional):** POST com payload final ao `webhook_url`.

## 🔐 Segurança & Limites

- **MAX_FILE_MB** (default 800) — recusa acima do limite com `413`.
- **ALLOWED_MIME** — recusa fora da lista com `415`.
- **CORS_ORIGINS** — default `*`, ajuste para domínios do seu n8n.
- **TTL** — apaga metadados após `TASK_TTL_HOURS` (arquivos ficam no Spaces).
- **Saneamento** — renomeia arquivo → `{task_id}.mp4`.
- **Observabilidade** — inclui `request_id` em headers/respostas.

## 🛠️ Tecnologias

- **FastAPI** — Framework web moderno e rápido
- **Celery + Redis** — Sistema de fila assíncrono
- **PyTorch** — Framework de ML (YOLO)
- **Ultralytics** — YOLO v11
- **OpenCV** — Processamento de imagem
- **FFmpeg** — Processamento de vídeo
- **boto3** — Cliente S3 (DigitalOcean Spaces)
- **Uvicorn** — Servidor ASGI

## 📁 Estrutura do Projeto

```
cod5-watermark-worker/
├── app/
│   ├── main.py                 # FastAPI e rotas
│   ├── core/
│   │   ├── queue.py            # Celery + fallback ThreadPool
│   │   ├── processor.py        # Pipeline: frames → YOLO → máscara → LAMA → render
│   │   ├── storage.py          # Spaces (upload/download/delete/url)
│   │   ├── status.py           # Persistência de status
│   │   ├── config.py           # Leitura de ENV e validações
│   │   └── utils.py            # IDs, tempo, logs, validação
│   └── models/
│       └── best.pt             # YOLO weights (baixado na build)
├── Dockerfile
├── requirements.txt
├── start.sh
├── .env.example
├── README.md
└── storage.json                # cache leve de status
```

## 🔚 Observações Finais

- Em **Apple Silicon**, `TORCH_DEVICE=mps` acelera bastante (PyTorch já suporta MPS).
- Para vídeos muito longos, use `FRAME_STRIDE=2` para acelerar (com pequena perda de fidelidade).
- Se houver `@username` além da logo Sora, considere treinar/estender YOLO (dataset do próprio repo) — ou aumentar `MASK_EXPAND`.
- Para **webhook** ao terminar, passe `webhook_url` no upload (útil no n8n).

## 📄 Licença

Este projeto é fornecido "como está", sem garantias.

---

**Desenvolvido para COD5**

