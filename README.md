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
YOLO_MAX_DET=10             # máximo de detecções por frame
YOLO_AGNOSTIC_NMS=True      # NMS agnóstico a classes
INPAINT_BLEND_ALPHA=0.85    # força do inpainting (0.0-1.0)
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
   - **YOLO** detecta marcas d'água **frame a frame** (até `max_det` por frame).
   - Expande máscaras por frame (`MASK_EXPAND`).
   - **LAMA** aplica inpainting com blending configurável (`blend_alpha`).
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

## 📖 Parâmetros Detalhados

### Parâmetros de Upload

#### `override_conf` (opcional, 0.05–0.8)
**O que faz:** Ajusta o threshold de confiança do detector YOLO. Valores menores detectam mais objetos (incluindo possíveis ruídos), valores maiores exigem maior certeza.

**Quando usar:**
- **Menor (0.05–0.2):** Marca d'água muito sutil, logo pequeno, vídeos com baixa qualidade.
- **Padrão (0.25):** Maioria dos casos — bom equilíbrio.
- **Maior (0.4–0.8):** Marca d'água bem visível, logs grandes, máxima precisão.

**Efeitos colaterais:** Valores muito baixos podem detectar falhas de compressão como marcas; valores muito altos podem perder marcas pequenas ou parcialmente transparentes.

#### `override_mask_expand` (opcional, 0–128 pixels)
**O que faz:** Expande a região detectada em pixels antes do inpainting, garantindo que bordas da marca também sejam removidas.

**Quando usar:**
- **Menor (0–10):** Marcas com bordas bem definidas, logo pequeno, vídeo HD+.
- **Padrão (18):** Maioria dos casos.
- **Maior (30–128):** Marcas com sombras/efeitos, logos grandes com blur, máxima cobertura.

**Efeitos colaterais:** Valores muito grandes podem remover conteúdo legítimo próximo à marca (por exemplo, texto ou objetos adjacentes).

#### `override_frame_stride` (opcional, ≥1)
**O que faz:** Processa apenas 1 a cada N frames. O inpainting é interpolado entre frames processados.

**Quando usar:**
- **1 (padrão):** Melhor qualidade, remove todas as marcas — recomendado para produção.
- **2–3:** Vídeos longos, menor custo computacional, pequena perda de precisão.
- **4+:** Apenas testes rápidos — qualidade reduzida significativamente.

**Efeitos colaterais:** Valores >1 causam "tearing" em marcas que se movem entre frames, marcas parciais ou "fantasma" em transições rápidas.

#### `webhook_url` (opcional, URL completa)
**O que faz:** Envia POST com o status completo quando a tarefa finaliza (sucesso ou erro).

**Quando usar:**
- Integrações n8n, Zapier, Make.com.
- Notificações externas (Slack, Discord, email).
- Workflows automatizados.

**Payload de sucesso:**
```json
{
  "task_id": "cod5_1730389012",
  "status": "completed",
  "spaces_output": "https://...",
  "progress": 100,
  ...
}
```

**Payload de erro:**
```json
{
  "task_id": "cod5_1730389012",
  "status": "error",
  "error_detail": "Mensagem descritiva",
  ...
}
```

**Efeitos colaterais:** Webhook falhando não afeta o processamento, mas o status HTTP e erro são registrados nos logs e no status da tarefa.

### Parâmetros Avançados (Novo)

#### `max_det` (opcional, 1-50, default: 10)
**O que faz:** Define o número máximo de marcas d'água que o YOLO pode detectar por frame.

**Quando usar:**
- **10 (padrão):** Maioria dos casos - detecta logos em topo, meio, rodapé
- **20-50:** Vídeos com múltiplas marcas repetidas ou sobrepostas
- **1-5:** Apenas uma marca principal conhecida (mais rápido)

**Combinação recomendada:** Use com `agnostic_nms=True` para detectar múltiplas instâncias da mesma marca.

#### `agnostic_nms` (opcional, bool, default: True)
**O que faz:** Habilita NMS (Non-Maximum Suppression) agnóstico a classes, permitindo detectar múltiplas instâncias da mesma marca d'água.

**Quando usar:**
- **True (padrão):** Detecta múltiplas logos idênticas (ex: rodapé esquerdo + direito)
- **False:** Apenas quando marca d'água é única e bem definida

**Efeito:** Com `False`, YOLO pode ignorar logos duplicadas no mesmo frame.

#### `blend_alpha` (opcional, 0.0-1.0, default: 0.85)
**O que faz:** Controla a intensidade da reconstrução. 1.0 aplica 100% do inpainting, valores menores misturam com o frame original.

**Quando usar:**
- **0.85 (padrão):** Suaviza bordas da reconstrução, resultado natural
- **0.90-1.0:** Marca muito forte, máxima remoção
- **0.70-0.80:** Marca sutil, preferência por preservar textura original

**Efeito visual:**
- `1.0`: Área reconstruída pode parecer "artificial" ou "borrada"
- `0.85`: Mistura suave, transição imperceptível
- `<0.7`: Marca residual visível (útil para testes)

### Combinações de Parâmetros

#### Cenário 1: Múltiplas logos (topo + rodapé)
```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -F "file=@video.mp4" \
  -F "max_det=20" \
  -F "agnostic_nms=true" \
  -F "blend_alpha=0.85"
```

#### Cenário 2: Marca d'água sutil
```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -F "file=@video.mp4" \
  -F "override_conf=0.15" \
  -F "override_mask_expand=24" \
  -F "blend_alpha=0.80"
```

#### Cenário 3: Logo grande e forte
```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -F "file=@video.mp4" \
  -F "override_conf=0.4" \
  -F "override_mask_expand=30" \
  -F "blend_alpha=0.95"
```

#### Cenário 4: Processamento rápido (trade-off qualidade)
```bash
curl -X POST "https://SEU_DOMINIO/submit_remove_task" \
  -F "file=@video.mp4" \
  -F "override_frame_stride=2" \
  -F "max_det=5"
```

### Variáveis de Ambiente

#### `TORCH_DEVICE` (cpu|mps|cuda)
**O que faz:** Acelera processamento com hardware dedicado.

**Quando usar:**
- **mps:** macOS com Apple Silicon (M1+) — **recomendado**.
- **cuda:** Linux/Windows com GPU NVIDIA RTX — **muito rápido**.
- **cpu:** Fallback ou máquinas sem GPU — mais lento.

**Nota:** O sistema detecta automaticamente se o device está disponível e ajusta para CPU se necessário.

#### `FRAME_STRIDE` (≥1, default: 1)
**Valor global** aplicado quando `override_frame_stride` não é fornecido. Mesmas regras acima.

#### `MASK_EXPAND` (≥0, default: 18)
**Valor global** aplicado quando `override_mask_expand` não é fornecido. Mesmas regras acima.

---

## 📊 Logs e Observabilidade

### Formato de Log

Os logs são emitidos em **JSON line** para facilitar parsing e filtragem:

```json
{"evt": "task.start", "timestamp": "2025-01-31T10:30:00Z", "task_id": "cod5_123"}
{"evt": "env.device", "timestamp": "...", "requested": "mps", "effective": "cpu", "ultralytics_version": "8.3.223"}
{"evt": "task.params", "timestamp": "...", "task_id": "cod5_123", "params_effective": {...}}
{"evt": "task.complete", "timestamp": "...", "task_id": "cod5_123", "total_duration_s": 33.5}
{"evt": "webhook.post_done", "timestamp": "...", "task_id": "cod5_123", "url": "...", "status": 200}
```

### Eventos Principais

| Evento | Descrição |
|--------|-----------|
| `task.start` | Início do processamento |
| `env.device` | Device PyTorch efetivo (com fallback) |
| `task.params` | Parâmetros aplicados (com defaults) |
| `task.download_done` | Vídeo baixado do Spaces |
| `task.extract_done` | Frames extraídos |
| `task.detect_done` | Marcas detectadas |
| `task.inpaint_done` | Inpainting concluído |
| `render.done` | Vídeo renderizado |
| `spaces.output` | Upload final concluído |
| `task.complete` | Processamento finalizado |
| `task.error` | Erro no processamento |
| `webhook.post` | Webhook sendo enviado |
| `webhook.post_done` | Webhook recebido |
| `webhook.post_error` | Falha no webhook |

### Filtrando Logs

**jq** (linha de comando):
```bash
docker logs container_name 2>&1 | jq 'select(.evt=="task.complete")'
docker logs container_name 2>&1 | jq 'select(.task_id=="cod5_123")'
```

**Loki/Grafana:** Configure parser JSON e use queries como `{evt="task.complete"}`.

---

## 🔧 Troubleshooting

### Status sempre "queued"

**Sintoma:** `/get_results` retorna `queued` mesmo após processamento completo.

**Causa:** Redis não configurado ou falha na conexão. Worker atualiza status em memória/arquivo local, mas API lê de outro local.

**Solução:** Configure `QUEUE_BACKEND=redis://...` e verifique logs de inicialização:
```
STATUS_BACKEND: Redis conectado com sucesso
```
Se não aparecer, o sistema usará fallback automático para `storage.json` (funciona, mas com limitações em multi-container).

### Erro 422: "override_frame_stride" inválido

**Sintoma:** Upload rejeitado com `422 Unprocessable Entity`.

**Causa:** Valor fora da faixa válida (ex.: `0`, negativo, `>10`, não-numérico).

**Solução:** Envie valores entre `1` e `10` (recomendado: `1`).

### Webhook não é chamado

**Sintoma:** `webhook_status` retorna `None` ou mostra erro.

**Possíveis causas:**
1. **URL inválida:** verifique sintaxe (deve ter `http://` ou `https://`).
2. **Timeout (10s):** servidor está lento ou inacessível.
3. **CORS:** servidor não aceita requests do worker.

**Solução:** Consulte `webhook_error` no status ou logs:
```bash
curl http://seu-dominio/get_results?task_id=cod5_123 | jq '.webhook_error'
```

### Processamento muito lento

**Sintoma:** Vídeos demoram minutos para processar.

**Causas e soluções:**
1. **CPU único:** configure `TORCH_DEVICE=cpu` (ou `cuda`/`mps` se disponível).
2. **Frames excessivos:** use `FRAME_STRIDE=2` ou `3`.
3. **Recursos insuficientes:** aumente CPU/RAM no container.

### Marca d'água não removida

**Sintoma:** Vídeo processado ainda mostra logo.

**Possíveis causas:**
1. **Modelo YOLO não detectou:** diminua `override_conf`.
2. **Área insuficiente:** aumente `override_mask_expand`.
3. **Marca animada:** use `FRAME_STRIDE=1` (padrão).
4. **Modelo incompatível:** verifique versão Ultralytics e logs de carregamento.

**Solução:** Teste com múltiplos valores de `conf` e `mask_expand` em vídeos curtos.

### Erro C3k2 no startup

**Sintoma:** `ERRO DE COMPATIBILIDADE C3k2` ao iniciar.

**Causa:** Versão incompatível do Ultralytics ou modelo requer código específico não presente.

**Solução:** O Dockerfile testa múltiplas versões automaticamente. Se persistir, verifique logs de build.

---

## 🔚 Observações Finais

- Em **Apple Silicon**, `TORCH_DEVICE=mps` acelera bastante (PyTorch já suporta MPS).
- Para vídeos muito longos, use `FRAME_STRIDE=2` para acelerar (com pequena perda de fidelidade).
- Se houver `@username` além da logo Sora, considere treinar/estender YOLO (dataset do próprio repo) — ou aumentar `MASK_EXPAND`.
- Para **webhook** ao terminar, passe `webhook_url` no upload (útil no n8n).
- Use **Redis** para produção multi-container — garante consistência de status entre workers.

## 📄 Licença

Este projeto é fornecido "como está", sem garantias.

---

**Desenvolvido para COD5**

