"""Utilitários gerais."""
import os
import json
import logging
import time
import uuid
import re
from typing import Optional
from pathlib import Path
from fastapi import UploadFile, HTTPException

from .config import settings

# Logger para logs estruturados
cod5_logger = logging.getLogger("cod5")
cod5_logger.setLevel(logging.INFO)


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
    """
    Valida tamanho do arquivo.
    
    Nota: Para uploads streaming, file.size pode ser None.
    Nesse caso, a validação de tamanho será feita durante o streaming.
    """
    # Para uploads streaming, file.size pode ser None
    # Não falhamos aqui - a validação real será feita durante o streaming
    if file.size is None:
        return  # Tamanho será validado durante a leitura do arquivo
    
    # Valida apenas se file.size estiver disponível
    if file.size == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    
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


def humanize_log_message(evt: str, data: dict) -> str:
    """
    Converte eventos técnicos em mensagens humanizadas e legíveis.
    
    Args:
        evt: Nome do evento
        data: Dados do evento
    
    Returns:
        Mensagem humanizada
    """
    task_id = data.get("task_id", "")
    task_prefix = f"[{task_id}] " if task_id else ""
    
    # Mapeamento de eventos para mensagens humanizadas
    messages = {
        "task.start": f"🚀 {task_prefix}Processamento iniciado",
        "task.download_start": f"📥 {task_prefix}Baixando vídeo do Spaces...",
        "task.download_done": f"✅ {task_prefix}Download concluído em {format_duration(data.get('duration_s', 0))}",
        "task.extract_start": f"🎬 {task_prefix}Extraindo frames do vídeo...",
        "task.extract_done": f"✅ {task_prefix}Extracção concluída: {data.get('frames_total', 0)} frames em {format_duration(data.get('duration_s', 0))}",
        "task.detect_inpaint_done": f"✅ {task_prefix}Processamento de frames concluído: {data.get('frames_processed', 0)} frames, {data.get('total_detections', 0)} marcas detectadas em {format_duration(data.get('duration_s', 0))}",
        "task.frame_read_error": f"⚠️  {task_prefix}Erro ao ler frame {data.get('frame_idx', '?')}",
        "render.done": f"✅ {task_prefix}Renderização concluída: {data.get('size_mb', 0):.2f}MB em {format_duration(data.get('duration_s', 0))}",
        "spaces.output": f"☁️  {task_prefix}Upload para Spaces concluído em {format_duration(data.get('duration_s', 0))}",
        "task.complete": f"🎉 {task_prefix}Processamento concluído com sucesso em {format_duration(data.get('total_duration_s', 0))}",
        "task.error": f"❌ {task_prefix}Erro no processamento: {data.get('error', 'Erro desconhecido')}",
        "webhook.post_done": f"📢 {task_prefix}Webhook enviado com sucesso",
        "webhook.post_error": f"⚠️  {task_prefix}Erro ao enviar webhook: {data.get('error', 'Erro desconhecido')}",
        "env.device": f"⚙️  Device: {data.get('requested', '?')} → {data.get('effective', '?')}",
        "task.params": f"⚙️  {task_prefix}Parâmetros configurados",
    }
    
    # Retorna mensagem humanizada ou evento original
    return messages.get(evt, f"{evt} {data}")


def cod5_log(evt: str, humanize: bool = True, **data):
    """
    Emite log estruturado em formato JSON line e opcionalmente humanizado.
    
    Args:
        evt: Nome do evento (ex: "task.start", "webhook.post")
        humanize: Se True, também emite mensagem humanizada
        **data: Dados adicionais do evento
    
    Exemplo:
        cod5_log("task.start", task_id="cod5_123", device="cpu", model="YOLOv11s")
    """
    log_entry = {
        "evt": evt,
        "timestamp": get_timestamp(),
        **data
    }
    
    # Sempre emite log estruturado (JSON)
    cod5_logger.info(json.dumps(log_entry))
    
    # Se humanize=True, também emite mensagem humanizada
    if humanize:
        humanized_msg = humanize_log_message(evt, data)
        cod5_logger.info(humanized_msg)

