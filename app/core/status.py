"""Gerenciamento de status de tarefas."""
import json
import logging
import time
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timezone, timedelta
import threading

from .config import settings
from .utils import get_timestamp

logger = logging.getLogger(__name__)


class TaskStatus:
    """Status de uma tarefa."""
    
    def __init__(
        self,
        task_id: str,
        status: str = "queued",
        progress: int = 0,
        stage: str = "uploading",
        **kwargs
    ):
        self.task_id = task_id
        self.status = status  # queued|processing|completed|error
        self.progress = progress  # 0-100
        self.stage = stage
        self.started_at: Optional[str] = None
        self.updated_at = get_timestamp()
        self.duration_seconds: float = 0.0
        self.model_used: Optional[str] = None
        self.frames_total: Optional[int] = None
        self.frames_done: Optional[int] = None
        self.spaces_input: Optional[str] = None
        self.spaces_output: Optional[str] = None
        self.log_excerpt: str = ""
        self.message: str = ""
        self.params_effective: Dict[str, Any] = {}
        self.error_detail: Optional[str] = None
        self.webhook_status: Optional[int] = None
        self.webhook_error: Optional[str] = None
        
        # Métricas de vídeo
        self.video_metadata: Dict[str, Any] = {}
        self.processing_metrics: Dict[str, Any] = {}
        self.performance_metrics: Dict[str, Any] = {}
        self.resource_usage: Dict[str, Any] = {}
        
        # Atualiza com kwargs
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def to_dict(self) -> dict:
        """Converte para dict."""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "duration_seconds": self.duration_seconds,
            "model_used": self.model_used,
            "frames_total": self.frames_total,
            "frames_done": self.frames_done,
            "spaces_input": self.spaces_input,
            "spaces_output": self.spaces_output,
            "log_excerpt": self.log_excerpt,
            "message": self.message,
            "params_effective": self.params_effective,
            "error_detail": self.error_detail,
            "webhook_status": self.webhook_status,
            "webhook_error": self.webhook_error,
            "video_metadata": self.video_metadata,
            "processing_metrics": self.processing_metrics,
            "performance_metrics": self.performance_metrics,
            "resource_usage": self.resource_usage,
        }
    
    def update(self, **kwargs) -> None:
        """Atualiza campos do status."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = get_timestamp()
        
        # Atualiza duration se started_at existir
        if self.started_at:
            try:
                start = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                self.duration_seconds = (now - start).total_seconds()
            except:
                pass


def _make_redis_key(task_id: str) -> str:
    """Gera chave Redis para status de tarefa."""
    return f"cod5:wm:status:{task_id}"


class StatusManager:
    """Gerencia status de todas as tarefas com Redis (prioritário) ou arquivo (fallback)."""
    
    def __init__(self):
        self._statuses: Dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self.storage_path = Path("storage.json")
        self._redis_client = None
        self._use_redis = False
        self._backend_name = "file"
        self._init_backend()
    
    def _init_backend(self) -> None:
        """Inicializa backend: tenta Redis primeiro, fallback para arquivo."""
        if not settings.is_redis_enabled():
            logger.info("STATUS_BACKEND: Redis não configurado, usando storage.json")
            self._backend_name = "file"
            self._load_from_storage()
            return
        
        try:
            import redis
            self._redis_client = redis.from_url(
                settings.QUEUE_BACKEND,
                decode_responses=True,
                socket_connect_timeout=3
            )
            # Testa conexão
            self._redis_client.ping()
            self._use_redis = True
            self._backend_name = "redis"
            logger.info(f"STATUS_BACKEND: Redis conectado com sucesso | URL: {settings.QUEUE_BACKEND}")
        except Exception as e:
            logger.warning(f"STATUS_BACKEND: Falha ao conectar Redis, usando fallback | Erro: {e}")
            self._redis_client = None
            self._use_redis = False
            self._backend_name = "file"
            self._load_from_storage()
    
    def _load_from_storage(self) -> None:
        """Carrega status do arquivo storage.json."""
        if not self.storage_path.exists():
            return
        
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                for task_id, status_data in data.items():
                    self._statuses[task_id] = TaskStatus(**status_data)
        except Exception as e:
            logger.error(f"Erro ao carregar storage.json: {e}")
    
    def _save_to_storage(self) -> None:
        """Salva status para storage.json (cache)."""
        try:
            data = {task_id: status.to_dict() for task_id, status in self._statuses.items()}
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar storage.json: {e}")
    
    def _save_to_redis(self, task_id: str, status_data: dict) -> None:
        """Salva status no Redis com TTL."""
        if not self._redis_client or not self._use_redis:
            return
        
        try:
            key = _make_redis_key(task_id)
            ttl_seconds = settings.TASK_TTL_HOURS * 3600
            json_data = json.dumps(status_data)
            self._redis_client.setex(key, ttl_seconds, json_data)
        except Exception as e:
            logger.error(f"Erro ao salvar no Redis: {e}")
    
    def _load_from_redis(self, task_id: str) -> Optional[dict]:
        """Carrega status do Redis."""
        if not self._redis_client or not self._use_redis:
            return None
        
        try:
            key = _make_redis_key(task_id)
            raw = self._redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.error(f"Erro ao carregar do Redis: {e}")
            return None
    
    def _delete_from_redis(self, task_id: str) -> None:
        """Remove status do Redis."""
        if not self._redis_client or not self._use_redis:
            return
        
        try:
            key = _make_redis_key(task_id)
            self._redis_client.delete(key)
        except Exception as e:
            logger.error(f"Erro ao deletar do Redis: {e}")
    
    def _list_from_redis(self, limit: int) -> list[dict]:
        """Lista tarefas recentes do Redis."""
        if not self._redis_client or not self._use_redis:
            return []
        
        try:
            pattern = "cod5:wm:status:*"
            keys = list(self._redis_client.scan_iter(match=pattern, count=limit * 2))
            
            tasks = []
            for key in keys[:limit * 2]:
                raw = self._redis_client.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        tasks.append({
                            "task_id": data.get("task_id"),
                            "status": data.get("status", "unknown"),
                            "progress": data.get("progress", 0),
                            "updated_at": data.get("updated_at"),
                        })
                    except:
                        pass
            
            # Ordena por updated_at desc
            tasks.sort(key=lambda t: t.get("updated_at") or "", reverse=True)
            return tasks[:limit]
        except Exception as e:
            logger.error(f"Erro ao listar do Redis: {e}")
            return []
    
    def create(self, task_id: str, **kwargs) -> TaskStatus:
        """Cria novo status."""
        status = TaskStatus(task_id, **kwargs)
        status.started_at = get_timestamp()
        
        if self._use_redis:
            # Salva diretamente no Redis
            status_dict = status.to_dict()
            self._save_to_redis(task_id, status_dict)
        else:
            # Salva em arquivo + memória
            with self._lock:
                self._statuses[task_id] = status
                self._save_to_storage()
        
        return status
    
    def get(self, task_id: str) -> Optional[TaskStatus]:
        """Retorna status de uma tarefa."""
        if self._use_redis:
            data = self._load_from_redis(task_id)
            if data:
                return TaskStatus(**data)
            return None
        else:
            with self._lock:
                return self._statuses.get(task_id)
    
    def update(self, task_id: str, **kwargs) -> None:
        """Atualiza status de uma tarefa."""
        if self._use_redis:
            # Carrega, atualiza, salva no Redis
            data = self._load_from_redis(task_id)
            if not data:
                return
            
            # Cria TaskStatus temporário para usar método update()
            temp_status = TaskStatus(**data)
            temp_status.update(**kwargs)
            
            # Salva de volta no Redis
            self._save_to_redis(task_id, temp_status.to_dict())
        else:
            with self._lock:
                if task_id in self._statuses:
                    self._statuses[task_id].update(**kwargs)
                    self._save_to_storage()
    
    def delete(self, task_id: str) -> None:
        """Remove status de uma tarefa."""
        if self._use_redis:
            self._delete_from_redis(task_id)
        else:
            with self._lock:
                if task_id in self._statuses:
                    del self._statuses[task_id]
                    self._save_to_storage()
    
    def list_recent(self, limit: int = 50) -> list[dict]:
        """Lista tarefas recentes."""
        if self._use_redis:
            return self._list_from_redis(limit)
        else:
            with self._lock:
                tasks = list(self._statuses.values())
                # Ordena por updated_at desc
                tasks.sort(key=lambda t: t.updated_at or "", reverse=True)
                return [{
                    "task_id": t.task_id,
                    "status": t.status,
                    "progress": t.progress,
                    "updated_at": t.updated_at,
                } for t in tasks[:limit]]
    
    def cleanup_old(self) -> None:
        """Remove tarefas antigas baseado em TTL."""
        # Redis já tem TTL automático, então só limpa arquivo se necessário
        if self._use_redis:
            # TTL está no Redis, não precisa limpar manualmente
            logger.debug("STATUS: cleanup_old ignorado (Redis com TTL automático)")
            return
        
        # Limpa arquivo local
        ttl_hours = settings.TASK_TTL_HOURS
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        
        with self._lock:
            to_remove = []
            for task_id, status in self._statuses.items():
                if status.updated_at:
                    try:
                        updated = datetime.fromisoformat(status.updated_at.replace('Z', '+00:00'))
                        if updated < cutoff:
                            to_remove.append(task_id)
                    except:
                        pass
            
            for task_id in to_remove:
                del self._statuses[task_id]
            
            if to_remove:
                self._save_to_storage()


# Instância global
status_manager = StatusManager()

