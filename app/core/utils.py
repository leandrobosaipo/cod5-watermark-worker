"""Utilitários gerais."""
import os
import time
import uuid
import re
from typing import Optional
from pathlib import Path
from fastapi import UploadFile, HTTPException

from .config import settings


def generate_task_id() -> str:
    """Gera task_id único no formato cod5_<timestamp>."""
    return f"cod5_{int(time.time())}"


def generate_request_id() -> str:
    """Gera request_id único."""
    return str(uuid.uuid4())


def sanitize_filename(filename: str) -> str:
    """Remove caracteres perigosos do nome do arquivo."""
    # Remove path traversal e caracteres especiais
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    return filename


def validate_file_size(file: UploadFile) -> None:
    """Valida tamanho do arquivo."""
    if not file.size:
        raise HTTPException(status_code=400, detail="Arquivo vazio ou tamanho desconhecido")
    
    max_bytes = settings.MAX_FILE_MB * 1024 * 1024
    if file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {settings.MAX_FILE_MB}MB"
        )


def validate_mime_type(file: UploadFile) -> None:
    """Valida tipo MIME do arquivo."""
    allowed = settings.get_allowed_mimes()
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de arquivo não permitido. Permitidos: {', '.join(allowed)}"
        )


def validate_file(file: UploadFile) -> None:
    """Valida arquivo completo."""
    validate_file_size(file)
    validate_mime_type(file)


def format_duration(seconds: float) -> str:
    """Formata duração em segundos para string legível."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m{secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h{mins}m"


def get_timestamp() -> str:
    """Retorna timestamp ISO 8601."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

