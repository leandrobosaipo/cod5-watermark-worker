"""FastAPI application - API para remoção de marcas d'água."""
import os
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field, HttpUrl
import tempfile

from .core.config import settings
from .core.storage import storage
from .core.utils import (
    generate_task_id,
    generate_request_id,
    validate_file,
    sanitize_filename
)
from .core.storage import storage
from .core.status import status_manager
from .core.queue import enqueue_video_processing
from .core.processor import process_video

# Configuração de logging detalhada e humanizada
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)8s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Configura logger específico da aplicação
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Logger para operações críticas
critical_logger = logging.getLogger(f"{__name__}.critical")

# FastAPI app
app = FastAPI(
    title="COD5 Watermark Worker",
    description="API para remoção de marcas d'água de vídeos Sora2",
    version="1.0.0"
)

# CORS
if settings.CORS_ORIGINS == "*":
    allow_origins = ["*"]
else:
    allow_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Schemas Pydantic para request/response
class SubmitResponse(BaseModel):
    """Resposta do endpoint de upload."""
    task_id: str = Field(..., example="cod5_1730389012", description="ID único da tarefa")
    status: str = Field(..., example="queued", description="Status inicial da tarefa")
    message: str = Field(..., example="Video received. Processing will start soon.", description="Mensagem descritiva")
    spaces_input: str = Field(..., example="https://cod5.nyc3.digitaloceanspaces.com/uploads/cod5_1730389012.mp4", description="URL do vídeo enviado")


class TaskResponse(BaseModel):
    """Resposta completa de status de tarefa."""
    task_id: str
    status: str
    progress: int
    stage: str
    started_at: Optional[str]
    updated_at: Optional[str]
    duration_seconds: float
    model_used: Optional[str]
    frames_total: Optional[int]
    frames_done: Optional[int]
    spaces_input: Optional[str]
    spaces_output: Optional[str]
    log_excerpt: str
    message: str
    params_effective: dict
    error_detail: Optional[str]
    webhook_status: Optional[int]
    webhook_error: Optional[str]


class TaskListItem(BaseModel):
    """Item da lista de tarefas."""
    task_id: str
    status: str
    progress: int
    updated_at: Optional[str]


@app.middleware("http")
async def add_request_id(request, call_next):
    """Adiciona request_id a todas as requisições."""
    import time
    request_id = generate_request_id()
    request.state.request_id = request_id
    start_time = time.time()
    
    # Log da requisição
    logger.info(f"🔵 REQUEST [{request.method}] {request.url.path} | Request-ID: {request_id}")
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        logger.info(
            f"🟢 RESPONSE [{request.method}] {request.url.path} | "
            f"Status: {response.status_code} | Duration: {duration:.3f}s | Request-ID: {request_id}"
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"🔴 ERROR [{request.method}] {request.url.path} | "
            f"Exception: {str(e)} | Duration: {duration:.3f}s | Request-ID: {request_id}"
        )
        raise


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "COD5 Watermark Worker",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.post(
    "/submit_remove_task",
    summary="Inicia processamento de vídeo (remoção de marcas d'água)",
    description=(
        "Recebe um vídeo e cria uma tarefa assíncrona para remoção de marcas d'água usando YOLO + LAMA.\n\n"
        "**Parâmetros principais:**\n"
        "- `override_conf`: Threshold de detecção (0.05-0.8). Menor=mais sensível.\n"
        "- `override_mask_expand`: Expansão da máscara em pixels (0-128). Maior=área maior removida.\n\n"
        "**Parâmetros avançados (novo):**\n"
        "- `max_det`: Máximo de marcas por frame (1-50). Permite detectar múltiplas logos.\n"
        "- `agnostic_nms`: Detecta múltiplas instâncias da mesma marca (True recomendado).\n"
        "- `blend_alpha`: Suavização do inpainting (0.0-1.0). 0.85=natural, 1.0=máxima remoção.\n\n"
        "**Combinação típica para múltiplas logos:**\n"
        "`max_det=20`, `agnostic_nms=true`, `blend_alpha=0.85`\n\n"
        "**Webhook (opcional):** Recebe POST ao concluir (sucesso ou erro)."
    ),
    response_model=SubmitResponse,
)
async def submit_remove_task(
    file: UploadFile = File(..., description="Vídeo .mp4|.mov|.avi (até MAX_FILE_MB)", example="video.mp4"),
    override_conf: Optional[float] = Form(
        None,
        ge=0.05,
        le=0.8,
        description="(opcional) Threshold do detector YOLO [0.05–0.8]. Valores menores detectam mais ruídos, maiores podem perder marcas.",
        example=0.25
    ),
    override_mask_expand: Optional[int] = Form(
        None,
        ge=0,
        le=128,
        description="(opcional) Expansão da máscara em pixels [0–128]. Valores maiores cobrem mais área ao redor da detecção.",
        example=18
    ),
    override_frame_stride: Optional[int] = Form(
        None,
        ge=1,
        description="(opcional) Intervalo de frames para processamento (≥1). 1=processa todos, 2=metade, etc. Aumenta velocidade mas reduz precisão.",
        example=1
    ),
    max_det: Optional[int] = Form(
        None,
        ge=1,
        le=50,
        description="(opcional) Máximo de marcas detectadas por frame [1-50]. Valores maiores detectam múltiplas logos (topo, meio, rodapé).",
        example=10
    ),
    agnostic_nms: Optional[bool] = Form(
        None,
        description="(opcional) NMS agnóstico a classes. True detecta múltiplas instâncias da mesma marca.",
        example=True
    ),
    blend_alpha: Optional[float] = Form(
        None,
        ge=0.0,
        le=1.0,
        description="(opcional) Força do inpainting [0.0-1.0]. 1.0=máxima reconstrução, 0.85=suavizado (recomendado), <0.7=marca residual.",
        example=0.85
    ),
    webhook_url: Optional[str] = Form(
        None,
        description="(opcional) URL que receberá POST ao finalizar (sucesso ou erro). Deve ser URL válida com protocolo.",
        example="https://exemplo.com/meu-webhook"
    )
):
    try:
        logger.info("📤 RECEIVED: Upload de vídeo iniciado")
        
        # Valida arquivo
        validate_file(file)
        logger.info(f"✅ VALIDATION: Arquivo validado | Nome: {file.filename} | Tipo: {file.content_type}")
        
        # Gera task_id
        task_id = generate_task_id()
        logger.info(f"🆔 TASK_CREATED: task_id={task_id}")
        
        # Salva arquivo temporariamente
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            # Upload para Spaces
            logger.info(f"📤 UPLOAD: Iniciando upload para Spaces | task_id={task_id}")
            spaces_key = f"uploads/{task_id}.mp4"
            spaces_url = storage.upload_file(tmp_path, spaces_key)
            logger.info(f"✅ UPLOAD: Vídeo enviado para Spaces | URL: {spaces_url} | task_id={task_id}")
            
            # Cria status inicial
            status_manager.create(
                task_id,
                status="queued",
                stage="uploading",
                progress=0,
                spaces_input=spaces_url,
                message="Video received. Processing will start soon."
            )
            logger.info(f"📊 STATUS: Status inicial criado | task_id={task_id} | status=queued")
            
            # Parâmetros do processamento
            # Valida e sanitiza webhook_url
            validated_webhook = None
            if webhook_url:
                webhook_url_clean = webhook_url.strip() if isinstance(webhook_url, str) else None
                if webhook_url_clean and webhook_url_clean.lower() != 'string' and len(webhook_url_clean) > 10:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(webhook_url_clean)
                        if parsed.scheme and parsed.netloc:
                            validated_webhook = webhook_url_clean
                        else:
                            logger.warning(f"⚠️  WEBHOOK: URL inválida ignorada | URL: {webhook_url} | task_id={task_id}")
                    except Exception as e:
                        logger.warning(f"⚠️  WEBHOOK: Erro ao validar URL | URL: {webhook_url} | Erro: {e} | task_id={task_id}")
            
            params = {
                "override_conf": override_conf,
                "override_mask_expand": override_mask_expand if override_mask_expand is not None else None,
                "override_frame_stride": override_frame_stride if override_frame_stride is not None else None,
                "max_det": max_det,
                "agnostic_nms": agnostic_nms,
                "blend_alpha": blend_alpha,
                "webhook_url": validated_webhook
            }
            logger.info(
                f"⚙️  PARAMS: Parâmetros configurados | "
                f"conf={override_conf if override_conf is not None else 'default'} | "
                f"mask_expand={override_mask_expand if override_mask_expand is not None else 'default'} | "
                f"stride={override_frame_stride if override_frame_stride is not None else 'default'} | "
                f"max_det={max_det if max_det is not None else 'default'} | "
                f"agnostic_nms={agnostic_nms if agnostic_nms is not None else 'default'} | "
                f"blend_alpha={blend_alpha if blend_alpha is not None else 'default'} | "
                f"webhook={'sim' if validated_webhook else 'não'} | "
                f"task_id={task_id}"
            )
            
            # Enfileira tarefa (Celery ou fallback ThreadPool)
            enqueue_video_processing(task_id, spaces_key, params)
            logger.info(f"🔄 QUEUE: Tarefa enfileirada | task_id={task_id}")
            
            result = {
                "task_id": task_id,
                "status": "queued",
                "message": "Video received. Processing will start soon.",
                "spaces_input": spaces_url
            }
            logger.info(f"✅ SUCCESS: Upload concluído com sucesso | task_id={task_id}")
            return result
        
        finally:
            # Remove arquivo temporário
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                logger.debug(f"🗑️  CLEANUP: Arquivo temporário removido | path={tmp_path}")
    
    except HTTPException as e:
        logger.warning(f"⚠️  HTTP_ERROR: {e.status_code} | Detail: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"🔴 ERROR: Erro ao processar upload | Exception: {type(e).__name__} | {str(e)}")
        logger.exception("Stack trace completo:")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")


@app.get(
    "/get_results",
    summary="Retorna status detalhado de uma tarefa",
    description="Consulta o status atual de uma tarefa, incluindo progresso, estágio, parâmetros efetivos e URLs de input/output.",
    response_model=TaskResponse,
)
async def get_results(task_id: str = Query(..., description="ID da tarefa", example="cod5_1730389012")):
    """
    Retorna status detalhado de uma tarefa.
    
    Query:
        - task_id: ID da tarefa (obrigatório)
    """
    status = status_manager.get(task_id)
    
    if not status:
        raise HTTPException(status_code=404, detail=f"Tarefa {task_id} não encontrada")
    
    return status.to_dict()


@app.get("/download/{task_id}")
async def download_task(task_id: str):
    """
    Redireciona para URL pública do vídeo processado no Spaces.
    
    Args:
        task_id: ID da tarefa
    """
    logger.info(f"📥 DOWNLOAD: Requisição de download | task_id={task_id}")
    
    status = status_manager.get(task_id)
    
    if not status:
        logger.warning(f"⚠️  DOWNLOAD: Tarefa não encontrada | task_id={task_id}")
        raise HTTPException(status_code=404, detail=f"Tarefa {task_id} não encontrada")
    
    logger.info(f"   Status da tarefa: {status.status} | Output: {'sim' if status.spaces_output else 'não'}")
    
    if status.status != "completed":
        logger.warning(
            f"⚠️  DOWNLOAD: Vídeo não está pronto | "
            f"Status: {status.status} | Progress: {status.progress}% | task_id={task_id}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Vídeo ainda não está pronto. Status: {status.status}, Progresso: {status.progress}%"
        )
    
    if not status.spaces_output:
        logger.error(f"❌ DOWNLOAD: URL de output não encontrada | task_id={task_id}")
        raise HTTPException(
            status_code=400,
            detail=f"URL do vídeo processado não encontrada. Status: {status.status}"
        )
    
    # Redireciona para URL pública do Spaces
    logger.info(f"✅ DOWNLOAD: Redirecionando para vídeo | URL: {status.spaces_output} | task_id={task_id}")
    return RedirectResponse(url=status.spaces_output, status_code=302)


@app.get(
    "/tasks",
    summary="Lista tarefas recentes",
    description="Retorna lista resumida das tarefas mais recentes ordenadas por atualização (descendente).",
    response_model=list[TaskListItem],
)
async def list_tasks(limit: int = Query(50, ge=1, le=100, description="Limite de tarefas", example=50)):
    """
    Lista tarefas recentes.
    
    Query:
        - limit: Número máximo de tarefas (1-100, default: 50)
    """
    tasks = status_manager.list_recent(limit=limit)
    return tasks


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """
    Remove tarefa e arquivos do Spaces.
    
    Args:
        task_id: ID da tarefa
    """
    status = status_manager.get(task_id)
    
    if not status:
        raise HTTPException(status_code=404, detail=f"Tarefa {task_id} não encontrada")
    
    # Remove arquivos do Spaces
    if status.spaces_input:
        try:
            input_key = status.spaces_input.split('/')[-1]
            if 'uploads/' in status.spaces_input:
                storage.delete_file(f"uploads/{input_key}")
        except Exception as e:
            logger.warning(f"Erro ao deletar input do Spaces: {e}")
    
    if status.spaces_output:
        try:
            output_key = status.spaces_output.split('/')[-1]
            if 'outputs/' in status.spaces_output:
                storage.delete_file(f"outputs/{output_key}")
        except Exception as e:
            logger.warning(f"Erro ao deletar output do Spaces: {e}")
    
    # Remove status local
    status_manager.delete(task_id)
    
    return {"message": f"Tarefa {task_id} deletada com sucesso"}


@app.get("/healthz")
async def healthz():
    """
    Health check com status de serviços.
    """
    import time
    import threading
    
    start_time = getattr(app.state, 'start_time', None)
    if start_time is None:
        app.state.start_time = time.time()
        start_time = app.state.start_time
    
    uptime = time.time() - start_time
    
    # Testa Spaces
    spaces_ok = storage.test_connection()
    
    # Testa Redis (se habilitado)
    redis_ok = None
    if settings.is_redis_enabled():
        try:
            import redis
            r = redis.from_url(settings.QUEUE_BACKEND)
            r.ping()
            redis_ok = "up"
        except Exception as e:
            logger.warning(f"Redis ping failed: {e}")
            redis_ok = "down"
    else:
        redis_ok = "not_configured"
    
    return {
        "ok": spaces_ok and (redis_ok != "down"),
        "redis": redis_ok,
        "spaces": "up" if spaces_ok else "down",
        "uptime_seconds": int(uptime)
    }


# Startup: limpeza de tarefas antigas
@app.on_event("startup")
async def startup_event():
    """Inicializa aplicação."""
    logger.info("=" * 80)
    logger.info("🚀 STARTUP: Iniciando COD5 Watermark Worker...")
    logger.info("=" * 80)
    
    # Validação crítica: versão do ultralytics
    logger.info("📦 CHECKING: Validando biblioteca Ultralytics...")
    try:
        import ultralytics
        uv_version = ultralytics.__version__
        logger.info(f"✅ ULTRA: Ultralytics instalado | Versão: {uv_version}")
        
        # Verifica compatibilidade tentando importar YOLO e verificar estrutura
        # Não verificamos C3k2 diretamente, deixamos o YOLO lidar com a compatibilidade
        try:
            from ultralytics import YOLO
            logger.info("✅ YOLO: Módulo YOLO importável com sucesso")
            
            # Tentativa opcional de verificar C3k2 (não crítico)
            try:
                from ultralytics.nn.modules.block import C3k2
                logger.info("✅ C3K2: Módulo C3k2 encontrado no ultralytics")
            except (ImportError, AttributeError, ModuleNotFoundError):
                logger.warning(
                    "⚠️  C3K2: Módulo C3k2 não encontrado diretamente, mas YOLO está disponível. "
                    "O modelo será testado durante o carregamento."
                )
        except ImportError as e:
            error_msg = f"❌ ERRO: Não foi possível importar YOLO: {e}"
            critical_logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        
        logger.info("✅ ULTRA: Validação de versão ultralytics concluída com sucesso")
    except ImportError as e:
        error_msg = f"❌ ERRO: Não foi possível importar ultralytics: {e}"
        critical_logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    
    # Valida device e verifica disponibilidade real
    logger.info("🎯 CHECKING: Validando dispositivo PyTorch...")
    effective_device = settings.validate_device()
    logger.info(f"✅ DEVICE: Device configurado: '{settings.TORCH_DEVICE}' | Device efetivo: '{effective_device}'")
    if effective_device != settings.TORCH_DEVICE.lower():
        logger.warning(
            f"⚠️  DEVICE: Device ajustado automaticamente | "
            f"Original: '{settings.TORCH_DEVICE}' → Efetivo: '{effective_device}' | "
            f"Motivo: dispositivo solicitado não está disponível no sistema"
        )
    
    # Valida conexão com Spaces
    logger.info("☁️  CHECKING: Validando conexão com DigitalOcean Spaces...")
    logger.info(f"   Configuração: Bucket={settings.SPACES_BUCKET} | Region={settings.SPACES_REGION} | Endpoint={settings.SPACES_ENDPOINT}")
    try:
        spaces_ok = storage.test_connection()
        if not spaces_ok:
            error_msg = "❌ ERRO: Não foi possível conectar ao DigitalOcean Spaces"
            critical_logger.error(error_msg)
            critical_logger.error("   Verifique: SPACES_KEY, SPACES_SECRET, SPACES_BUCKET e SPACES_ENDPOINT")
            raise RuntimeError("Falha na conexão com Spaces")
        logger.info("✅ SPACES: Conexão com DigitalOcean Spaces validada com sucesso")
    except Exception as e:
        error_msg = f"❌ ERRO: Falha ao validar Spaces | Exception: {type(e).__name__} | {str(e)}"
        critical_logger.error(error_msg)
        critical_logger.error("   Ação: Verifique as credenciais e configurações do Spaces")
        raise RuntimeError(f"Falha na validação do Spaces: {e}") from e
    
    # Valida Redis se configurado
    if settings.is_redis_enabled():
        logger.info("🔄 CHECKING: Validando conexão com Redis...")
        logger.info(f"   Configuração: {settings.QUEUE_BACKEND}")
        try:
            import redis
            r = redis.from_url(settings.QUEUE_BACKEND, socket_connect_timeout=5)
            r.ping()
            logger.info("✅ REDIS: Conexão com Redis validada com sucesso")
            logger.info(f"   Worker: Celery será usado com concurrency={settings.CELERY_CONCURRENCY}")
        except Exception as e:
            error_msg = f"❌ ERRO: Não foi possível conectar ao Redis | Exception: {type(e).__name__} | {str(e)}"
            critical_logger.error(error_msg)
            critical_logger.error("   Ação: Verifique QUEUE_BACKEND ou remova para usar fallback ThreadPool")
            raise RuntimeError(f"Falha na conexão com Redis: {e}") from e
    else:
        logger.info("⚠️  QUEUE: Redis não configurado | Usando ThreadPool (fallback)")
        logger.info(f"   Concurrency: {settings.CELERY_CONCURRENCY} workers")
    
    # Valida modelo YOLO existe
    logger.info("🤖 CHECKING: Validando modelo YOLO...")
    if not os.path.exists(settings.YOLO_MODEL_PATH):
        error_msg = f"❌ ERRO: Modelo YOLO não encontrado | Path: {settings.YOLO_MODEL_PATH}"
        critical_logger.error(error_msg)
        raise FileNotFoundError(f"Modelo YOLO não encontrado: {settings.YOLO_MODEL_PATH}")
    logger.info(f"✅ MODEL: Modelo YOLO encontrado | Path: {settings.YOLO_MODEL_PATH}")
    
    # Tenta pré-carregar modelo (opcional - não falha se der erro)
    logger.info("🤖 LOADING: Tentando pré-carregar modelo YOLO (isso pode demorar alguns segundos)...")
    try:
        from .core.processor import get_yolo_model
        model = get_yolo_model()
        logger.info("✅ MODEL: Modelo YOLO pré-carregado com sucesso | Pronto para processar vídeos")
    except Exception as e:
        logger.warning(f"⚠️  MODEL: Não foi possível pré-carregar modelo YOLO | Exception: {type(e).__name__} | {str(e)}")
        logger.warning("   O modelo será carregado na primeira requisição (pode causar delay)")
    
    # Limpeza inicial
    logger.info("🧹 CLEANUP: Limpando tarefas antigas...")
    status_manager.cleanup_old()
    logger.info("✅ CLEANUP: Limpeza de tarefas antigas concluída")
    
    logger.info("=" * 80)
    logger.info("✅ STARTUP: COD5 Watermark Worker iniciado com sucesso!")
    logger.info("=" * 80)


# Shutdown
@app.on_event("shutdown")
async def shutdown_event():
    """Finaliza aplicação."""
    logger.info("=" * 80)
    logger.info("🛑 SHUTDOWN: Encerrando COD5 Watermark Worker...")
    logger.info("=" * 80)

