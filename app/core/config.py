"""Configuração centralizada via variáveis de ambiente."""
import os
from typing import Optional

try:
    from pydantic_settings import BaseSettings
except ImportError:
    # Fallback para versões mais antigas
    try:
        from pydantic import BaseSettings
    except ImportError:
        raise ImportError("pydantic-settings ou pydantic é necessário. Instale: pip install pydantic-settings")


class Settings(BaseSettings):
    """Configurações da aplicação."""
    
    # API
    API_PORT: int = 5344
    CORS_ORIGINS: str = "*"
    
    # Queue
    QUEUE_BACKEND: Optional[str] = None  # redis://redis:6379/0 ou vazio para fallback
    CELERY_CONCURRENCY: int = 2
    
    # Spaces
    SPACES_REGION: str = "nyc3"
    SPACES_ENDPOINT: str = "https://nyc3.digitaloceanspaces.com"
    SPACES_BUCKET: str = "cod5"
    SPACES_KEY: str = ""
    SPACES_SECRET: str = ""
    
    # Modelos & Device
    YOLO_MODEL_PATH: str = "/app/models/best.pt"
    TORCH_DEVICE: str = "mps"  # cpu|mps|cuda
    YOLO_CONF: float = 0.25  # 0.05–0.8
    YOLO_IOU: float = 0.45  # 0.1–0.9
    MASK_EXPAND: int = 18  # pixels
    FRAME_STRIDE: int = 1  # 1 = todos os frames
    
    # Limites & housekeeping
    MAX_FILE_MB: int = 800
    ALLOWED_MIME: str = "video/mp4,video/quicktime,video/x-msvideo"
    TASK_TTL_HOURS: int = 72
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    def validate_device(self) -> str:
        """
        Valida e retorna device válido, verificando disponibilidade real.
        MPS só funciona no macOS, CUDA requer GPU NVIDIA.
        """
        device = self.TORCH_DEVICE.lower()
        
        # Valida formato básico
        if device not in ["cpu", "mps", "cuda"]:
            return "cpu"
        
        # Verifica disponibilidade real
        try:
            import torch
            
            if device == "mps":
                # MPS só funciona no macOS/Apple Silicon
                if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    return "mps"
                else:
                    import logging
                    logging.warning(
                        "TORCH_DEVICE=mps configurado, mas MPS não está disponível "
                        "(requer macOS com Apple Silicon). Usando CPU."
                    )
                    return "cpu"
            
            elif device == "cuda":
                # CUDA requer GPU NVIDIA
                if torch.cuda.is_available():
                    return "cuda"
                else:
                    import logging
                    logging.warning(
                        "TORCH_DEVICE=cuda configurado, mas CUDA não está disponível "
                        "(requer GPU NVIDIA). Usando CPU."
                    )
                    return "cpu"
            
            # CPU sempre disponível
            return "cpu"
            
        except ImportError:
            # Se torch não estiver disponível, retorna CPU (será erro depois)
            return device if device == "cpu" else "cpu"
    
    def validate_yolo_conf(self, value: Optional[float] = None) -> float:
        """Valida YOLO confidence."""
        conf = value or self.YOLO_CONF
        return max(0.05, min(0.8, conf))
    
    def validate_yolo_iou(self, value: Optional[float] = None) -> float:
        """Valida YOLO IOU."""
        iou = value or self.YOLO_IOU
        return max(0.1, min(0.9, iou))
    
    def get_allowed_mimes(self) -> list[str]:
        """Retorna lista de MIME types permitidos."""
        return [m.strip() for m in self.ALLOWED_MIME.split(",")]
    
    def is_redis_enabled(self) -> bool:
        """Verifica se Redis está habilitado."""
        return self.QUEUE_BACKEND is not None and self.QUEUE_BACKEND.startswith("redis://")


settings = Settings()

