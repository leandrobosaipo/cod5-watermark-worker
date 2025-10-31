"""Sistema de fila: Celery (Redis) ou fallback ThreadPool."""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any
import threading

from .config import settings

logger = logging.getLogger(__name__)

# Variáveis globais para fallback
_fallback_executor: Optional[ThreadPoolExecutor] = None
_fallback_lock = threading.Lock()

# Celery app (inicializado condicionalmente)
celery_app = None


def init_celery() -> Optional[Any]:
    """Inicializa Celery se Redis estiver disponível."""
    if not settings.is_redis_enabled():
        return None
    
    try:
        from celery import Celery
        
        app = Celery(
            'cod5_watermark_worker',
            broker=settings.QUEUE_BACKEND,
            backend=settings.QUEUE_BACKEND
        )
        app.conf.task_serializer = 'json'
        app.conf.accept_content = ['json']
        app.conf.result_serializer = 'json'
        app.conf.timezone = 'UTC'
        app.conf.enable_utc = True
        
        logger.info(f"Celery inicializado com Redis: {settings.QUEUE_BACKEND}")
        return app
    except Exception as e:
        logger.warning(f"Falha ao inicializar Celery: {e}")
        return None


def get_fallback_executor() -> ThreadPoolExecutor:
    """Retorna executor ThreadPool para fallback."""
    global _fallback_executor
    with _fallback_lock:
        if _fallback_executor is None:
            _fallback_executor = ThreadPoolExecutor(max_workers=settings.CELERY_CONCURRENCY)
            logger.info(f"ThreadPoolExecutor criado (max_workers={settings.CELERY_CONCURRENCY})")
        return _fallback_executor


def enqueue_task(task_func, *args, **kwargs):
    """
    Enfileira tarefa usando Celery ou fallback.
    
    Args:
        task_func: Função a executar
        *args, **kwargs: Argumentos para a função
    
    Returns:
        Celery AsyncResult ou Future (fallback)
    """
    global celery_app
    
    # Tenta inicializar Celery na primeira chamada
    if celery_app is None:
        celery_app = init_celery()
    
    if celery_app is not None:
        # Usa Celery
        task = celery_app.task(task_func)
        return task.delay(*args, **kwargs)
    else:
        # Fallback: ThreadPoolExecutor
        executor = get_fallback_executor()
        return executor.submit(task_func, *args, **kwargs)


# Inicializa Celery se possível
celery_app = init_celery()

# Task Celery (se disponível)
if celery_app is not None:
    @celery_app.task(name='process_video_task')
    def process_video_task(task_id: str, spaces_key: str, params: Dict[str, Any]):
        """
        Task Celery para processamento de vídeo.
        Esta função será chamada pelo worker Celery.
        """
        from .processor import process_video
        return process_video(task_id, spaces_key, params)

