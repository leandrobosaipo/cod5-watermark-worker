"""FastAPI application - API para remoção de marcas d'água."""
import os
import logging
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
import tempfile

from .core.config import settings
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

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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


@app.middleware("http")
async def add_request_id(request, call_next):
    """Adiciona request_id a todas as requisições."""
    request_id = generate_request_id()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "COD5 Watermark Worker",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.post("/submit_remove_task")
async def submit_remove_task(
    file: UploadFile = File(...),
    override_conf: Optional[float] = Form(None),
    override_mask_expand: Optional[int] = Form(None),
    override_frame_stride: Optional[int] = Form(None),
    webhook_url: Optional[str] = Form(None)
):
    """
    Recebe vídeo, envia para Spaces e enfileira processamento.
    
    Form-Data:
        - file: Vídeo (obrigatório)
        - override_conf: Confiança YOLO (0.05-0.8)
        - override_mask_expand: Pixels para expandir máscara
        - override_frame_stride: Intervalo entre frames (≥1)
        - webhook_url: URL para POST ao concluir/erro
    """
    try:
        # Valida arquivo
        validate_file(file)
        
        # Gera task_id
        task_id = generate_task_id()
        
        # Salva arquivo temporariamente
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_path = tmp_file.name
        
        try:
            # Upload para Spaces
            spaces_key = f"uploads/{task_id}.mp4"
            spaces_url = storage.upload_file(tmp_path, spaces_key)
            
            # Cria status inicial
            status_manager.create(
                task_id,
                status="queued",
                stage="uploading",
                progress=0,
                spaces_input=spaces_url,
                message="Video received. Processing will start soon."
            )
            
            # Parâmetros do processamento
            params = {
                "override_conf": override_conf,
                "override_mask_expand": override_mask_expand,
                "override_frame_stride": override_frame_stride,
                "webhook_url": webhook_url
            }
            
            # Enfileira tarefa (Celery ou fallback ThreadPool)
            enqueue_video_processing(task_id, spaces_key, params)
            
            return {
                "task_id": task_id,
                "status": "queued",
                "message": "Video received. Processing will start soon.",
                "spaces_input": spaces_url
            }
        
        finally:
            # Remove arquivo temporário
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao processar upload: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")


@app.get("/get_results")
async def get_results(task_id: str = Query(..., description="ID da tarefa")):
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
    status = status_manager.get(task_id)
    
    if not status:
        raise HTTPException(status_code=404, detail=f"Tarefa {task_id} não encontrada")
    
    if status.status != "completed" or not status.spaces_output:
        raise HTTPException(
            status_code=400,
            detail=f"Vídeo ainda não está pronto (status: {status.status})"
        )
    
    # Redireciona para URL pública do Spaces
    return RedirectResponse(url=status.spaces_output, status_code=302)


@app.get("/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=100, description="Limite de tarefas")):
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
    logger.info("Iniciando COD5 Watermark Worker...")
    
    # Validação crítica: versão do ultralytics
    try:
        import ultralytics
        uv_version = ultralytics.__version__
        logger.info(f"Ultralytics version: {uv_version}")
        
        # Verifica se C3k2 está disponível (mais importante que versão exata)
        try:
            from ultralytics.nn.modules.block import C3k2
            logger.info("✓ Módulo C3k2 encontrado no ultralytics")
        except ImportError:
            error_msg = (
                f"ERRO CRÍTICO: Módulo C3k2 não encontrado no ultralytics!\n"
                f"Versão instalada: {uv_version}\n"
                f"O modelo best.pt requer uma versão do ultralytics com C3k2.\n"
                f"Teste versões: 8.0.0, 8.0.100, 8.0.20, 8.0.10"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        logger.info("✓ Validação de versão ultralytics OK")
    except ImportError as e:
        error_msg = f"ERRO: Não foi possível importar ultralytics: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    
    logger.info(f"Device: {settings.validate_device()}")
    logger.info(f"Queue backend: {settings.QUEUE_BACKEND or 'ThreadPool (fallback)'}")
    
    # Limpeza inicial
    status_manager.cleanup_old()
    logger.info("Limpeza de tarefas antigas concluída")


# Shutdown
@app.on_event("shutdown")
async def shutdown_event():
    """Finaliza aplicação."""
    logger.info("Encerrando COD5 Watermark Worker...")

