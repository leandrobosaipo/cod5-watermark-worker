"""Gerenciamento de status de tarefas."""
import json
import time
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timezone, timedelta
import threading

from .config import settings
from .utils import get_timestamp


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


class StatusManager:
    """Gerencia status de todas as tarefas."""
    
    def __init__(self):
        self._statuses: Dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self.storage_path = Path("storage.json")
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
            print(f"Erro ao carregar storage.json: {e}")
    
    def _save_to_storage(self) -> None:
        """Salva status para storage.json (cache)."""
        try:
            data = {task_id: status.to_dict() for task_id, status in self._statuses.items()}
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Erro ao salvar storage.json: {e}")
    
    def create(self, task_id: str, **kwargs) -> TaskStatus:
        """Cria novo status."""
        with self._lock:
            status = TaskStatus(task_id, **kwargs)
            status.started_at = get_timestamp()
            self._statuses[task_id] = status
            self._save_to_storage()
            return status
    
    def get(self, task_id: str) -> Optional[TaskStatus]:
        """Retorna status de uma tarefa."""
        with self._lock:
            return self._statuses.get(task_id)
    
    def update(self, task_id: str, **kwargs) -> None:
        """Atualiza status de uma tarefa."""
        with self._lock:
            if task_id in self._statuses:
                self._statuses[task_id].update(**kwargs)
                self._save_to_storage()
    
    def delete(self, task_id: str) -> None:
        """Remove status de uma tarefa."""
        with self._lock:
            if task_id in self._statuses:
                del self._statuses[task_id]
                self._save_to_storage()
    
    def list_recent(self, limit: int = 50) -> list[dict]:
        """Lista tarefas recentes."""
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

