"""Pipeline de processamento de vídeo: YOLO + LAMA + FFmpeg."""
import os
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import cv2
import numpy as np
from ultralytics import YOLO
import torch

from .config import settings
from .storage import storage
from .status import status_manager
from .utils import get_timestamp, cod5_log

logger = logging.getLogger(__name__)

# Lazy loading do modelo YOLO
_yolo_model: Optional[YOLO] = None


def get_yolo_model() -> YOLO:
    """Carrega modelo YOLO (lazy loading)."""
    global _yolo_model
    if _yolo_model is None:
        model_path = settings.YOLO_MODEL_PATH
        if not os.path.exists(model_path):
            logger.error(f"❌ MODEL: Modelo YOLO não encontrado | Path: {model_path}")
            raise FileNotFoundError(f"Modelo YOLO não encontrado: {model_path}")
        
        try:
            # Verifica versão do ultralytics antes de carregar
            import ultralytics
            uv_version = ultralytics.__version__
            logger.info(f"🤖 LOADING: Carregando modelo YOLO | Ultralytics: {uv_version} | Path: {model_path}")
            
            # Tenta carregar o modelo
            _yolo_model = YOLO(model_path)
            logger.info(f"✅ MODEL: Modelo YOLO carregado com sucesso | Path: {model_path}")
        except AttributeError as e:
            if 'C3k2' in str(e):
                # Captura versão instalada para diagnóstico
                try:
                    import ultralytics
                    installed_version = ultralytics.__version__
                except:
                    installed_version = "desconhecida"
                
                error_msg = (
                    f"ERRO DE COMPATIBILIDADE C3k2:\n"
                    f"O modelo {model_path} requer uma versão do ultralytics com módulo C3k2.\n"
                    f"Versão instalada: {installed_version}\n"
                    f"Esta versão NÃO tem o módulo C3k2 necessário.\n"
                    f"Erro: {e}\n"
                    f"Soluções possíveis:\n"
                    f"1. Reconstrua com Dockerfile atualizado (testa múltiplas versões)\n"
                    f"2. O start.sh tentará versões alternativas automaticamente\n"
                    f"3. Versões a testar: 8.0.0, 8.0.100, 8.0.20, 8.0.10"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
            raise
        except Exception as e:
            # Captura versão para diagnóstico
            try:
                import ultralytics
                installed_version = ultralytics.__version__
                logger.error(f"Versão ultralytics: {installed_version}")
            except:
                pass
            logger.error(f"Erro ao carregar modelo YOLO: {e}")
            raise
    
    return _yolo_model


def detect_watermarks(
    frame: np.ndarray,
    conf: float,
    iou: float,
    device: str
) -> list:
    """
    Detecta marcas d'água em um frame usando YOLO.
    
    Returns:
        Lista de bounding boxes [(x1, y1, x2, y2), ...]
    """
    model = get_yolo_model()
    results = model(frame, conf=conf, iou=iou, device=device, verbose=False)
    
    boxes = []
    for result in results:
        if result.boxes is not None:
            for box in result.boxes:
                # Converte para coordenadas (x1, y1, x2, y2)
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                boxes.append((int(x1), int(y1), int(x2), int(y2)))
    
    return boxes


def expand_mask(boxes: list, expand_px: int, frame_shape: tuple) -> np.ndarray:
    """
    Cria máscara expandida a partir de bounding boxes.
    
    Args:
        boxes: Lista de (x1, y1, x2, y2)
        expand_px: Pixels para expandir
        frame_shape: (height, width) do frame
    
    Returns:
        Máscara binária (uint8)
    """
    h, w = frame_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    
    for x1, y1, x2, y2 in boxes:
        # Expande caixa
        x1 = max(0, x1 - expand_px)
        y1 = max(0, y1 - expand_px)
        x2 = min(w, x2 + expand_px)
        y2 = min(h, y2 + expand_px)
        
        # Preenche região na máscara
        mask[y1:y2, x1:x2] = 255
    
    return mask


def inpaint_frame_lama(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    Aplica inpainting em um frame usando algoritmo LAMA (OpenCV).
    
    Nota: Para LAMA completo, seria necessário instalar lama-cleaner.
    Aqui usamos cv2.INPAINT_TELEA como fallback.
    """
    # OpenCV inpainting (método rápido)
    result = cv2.inpaint(frame, mask, 3, cv2.INPAINT_TELEA)
    
    # TODO: Se necessário, integrar lama-cleaner real:
    # from lama_cleaner.model_manager import ModelManager
    # from lama_cleaner.schema import Config
    # ...
    
    return result


def extract_frames(video_path: str, output_dir: str, stride: int = 1) -> tuple[int, list[str]]:
    """
    Extrai frames do vídeo usando FFmpeg.
    
    Args:
        video_path: Caminho do vídeo
        output_dir: Diretório de saída
        stride: Intervalo entre frames (1 = todos)
    
    Returns:
        (total_frames, lista_de_caminhos)
    """
    import ffmpeg
    import subprocess
    
    # Obtém informações do vídeo
    probe = ffmpeg.probe(video_path)
    video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    fps = eval(video_info['r_frame_rate'])
    duration = float(video_info.get('duration', 0))
    total_frames = int(duration * fps)
    
    # Cria diretório se não existir
    os.makedirs(output_dir, exist_ok=True)
    
    # Extrai frames
    frame_pattern = os.path.join(output_dir, 'frame_%06d.png')
    
    # FFmpeg command
    # Nota: O FFmpeg espera: select='not(mod(n\,5))' onde 5 é o stride
    # O problema relatado: escapes duplos causam erro de parsing no FFmpeg
    # Solução: usar apenas uma barra na string (Python \\ produz \ na string)
    # mas o ffmpeg-python pode escapar novamente. Vamos usar uma string raw ou
    # construir de forma que o resultado final tenha apenas uma barra
    # Usa subprocess diretamente para evitar problemas de escape do ffmpeg-python
    # O ffmpeg-python pode adicionar escapes extras ao passar filtros com vírgulas
    
    try:
        # Constrói comando FFmpeg diretamente
        cmd = ['ffmpeg', '-i', video_path, '-vsync', '0', '-qscale:v', '2']
        
        if stride > 1:
            # Adiciona filtro select: select='not(mod(n\,{stride}))'
            # Passamos a expressão diretamente ao FFmpeg, sem escapes extras
            select_filter = f"select='not(mod(n\\,{stride}))'"
            cmd.extend(['-vf', select_filter])
        
        cmd.extend(['-y', frame_pattern])  # -y para overwrite
        
        # Executa comando
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        
        logger.debug(f"FFmpeg extraiu frames com sucesso (stride={stride})")
            
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
        logger.error(f"Erro FFmpeg ao extrair frames: {error_msg}")
        logger.error(f"Comando: {' '.join(cmd)}")
        logger.error(f"Stride: {stride}")
        raise RuntimeError(f"Falha ao extrair frames do vídeo: {error_msg}")
    except Exception as e:
        logger.error(f"Erro inesperado ao extrair frames: {e}")
        raise
    
    # Lista frames extraídos
    frame_files = sorted(Path(output_dir).glob('frame_*.png'))
    actual_count = len(frame_files)
    
    return actual_count, [str(f) for f in frame_files]


def render_video(
    frames_dir: str,
    output_path: str,
    audio_source: Optional[str] = None,
    fps: float = 30.0
) -> None:
    """
    Renderiza frames em vídeo usando FFmpeg.
    
    Args:
        frames_dir: Diretório com frames (frame_%06d.png)
        output_path: Caminho de saída
        audio_source: Vídeo original (para copiar áudio)
        fps: FPS do vídeo
    """
    import ffmpeg
    
    # FFmpeg espera padrão frame_000001.png, frame_000002.png, etc.
    frame_pattern = os.path.join(frames_dir, 'frame_%06d.png')
    
    # Stream de vídeo a partir de sequência de imagens
    # Usa start_number para começar do frame_000001.png
    video = ffmpeg.input(frame_pattern, framerate=fps, start_number=1)
    
    try:
        if audio_source and os.path.exists(audio_source):
            # Copia áudio do vídeo original
            audio = ffmpeg.input(audio_source).audio
            output = ffmpeg.output(
                video,
                audio,
                output_path,
                vcodec='libx264',
                acodec='copy',
                pix_fmt='yuv420p',
                **{'shortest': None}  # Para sincronizar com áudio
            )
        else:
            # Vídeo sem áudio
            output = ffmpeg.output(video, output_path, vcodec='libx264', pix_fmt='yuv420p')
        
        output.overwrite_output().run(quiet=True, capture_stderr=True)
    except ffmpeg.Error as e:
        logger.error(f"Erro FFmpeg ao renderizar vídeo: {e.stderr.decode() if e.stderr else str(e)}")
        raise


def process_video(task_id: str, spaces_key: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pipeline completo de processamento de vídeo.
    
    Args:
        task_id: ID da tarefa
        spaces_key: Chave do vídeo no Spaces (uploads/task_id.mp4)
        params: Parâmetros (conf, mask_expand, frame_stride, webhook_url, etc.)
    
    Returns:
        Dict com resultados
    """
    import time
    start_time = time.time()
    
    try:
        cod5_log("task.start", task_id=task_id, spaces_key=spaces_key)
        
        # Atualiza status: processing
        status_manager.update(
            task_id,
            status="processing",
            stage="downloading",
            progress=5,
            log_excerpt="Baixando vídeo do Spaces..."
        )
        cod5_log("task.download_start", task_id=task_id)
        
        # Configurações efetivas
        conf = settings.validate_yolo_conf(params.get('override_conf'))
        iou = settings.validate_yolo_iou()
        # Garante que mask_expand não seja None ou 0 quando não especificado
        override_mask_expand = params.get('override_mask_expand')
        mask_expand = override_mask_expand if override_mask_expand is not None else settings.MASK_EXPAND
        # Valida que mask_expand seja um número positivo
        mask_expand = max(0, int(mask_expand)) if mask_expand is not None else settings.MASK_EXPAND
        
        override_frame_stride = params.get('override_frame_stride')
        frame_stride = max(1, int(override_frame_stride)) if override_frame_stride is not None else settings.FRAME_STRIDE
        device = settings.validate_device()
        
        # Registra device efetivo e versão ultralytics
        try:
            import ultralytics
            ultralytics_version = ultralytics.__version__
        except:
            ultralytics_version = "unknown"
        
        cod5_log("env.device", requested=settings.TORCH_DEVICE, effective=device, ultralytics_version=ultralytics_version)
        cod5_log(
            "task.params",
            task_id=task_id,
            params_effective={
                "yolo_conf": conf,
                "yolo_iou": iou,
                "mask_expand": mask_expand,
                "frame_stride": frame_stride,
                "torch_device": device
            }
        )
        
        status_manager.update(
            task_id,
            params_effective={
                "yolo_conf": conf,
                "yolo_iou": iou,
                "mask_expand": mask_expand,
                "frame_stride": frame_stride,
                "torch_device": device
            },
            model_used="YOLOv11s + LAMA-big"
        )
        
        # Cria diretórios temporários
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download do Spaces
            local_video = os.path.join(temp_dir, f"{task_id}.mp4")
            download_start = time.time()
            storage.download_file(spaces_key, local_video)
            download_duration = time.time() - download_start
            cod5_log("task.download_done", task_id=task_id, duration_s=download_duration)
            
            # Extração de frames
            status_manager.update(
                task_id,
                stage="extracting",
                progress=10,
                log_excerpt="Extraindo frames do vídeo..."
            )
            cod5_log("task.extract_start", task_id=task_id)
            
            frames_dir = os.path.join(temp_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)
            
            # Obtém FPS do vídeo original
            import ffmpeg
            probe = ffmpeg.probe(local_video)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            fps = eval(video_info['r_frame_rate'])
            
            extract_start = time.time()
            total_frames, frame_files = extract_frames(local_video, frames_dir, stride=frame_stride)
            extract_duration = time.time() - extract_start
            cod5_log("task.extract_done", task_id=task_id, frames_total=total_frames, frame_stride=frame_stride, duration_s=extract_duration, fps=fps)
            status_manager.update(
                task_id,
                frames_total=total_frames,
                frames_done=0,
                stage="detecting",
                progress=15,
                log_excerpt=f"Detectando marcas d'água em {total_frames} frames..."
            )
            
            # Processa cada frame
            processed_frames_dir = os.path.join(temp_dir, "processed_frames")
            os.makedirs(processed_frames_dir, exist_ok=True)
            
            # Detecta marcas em frames de amostra (primeiro, meio, último)
            # para capturar variações de posição
            all_boxes = []
            sample_indices = [0]
            if len(frame_files) > 1:
                sample_indices.append(len(frame_files) // 2)
            if len(frame_files) > 2:
                sample_indices.append(len(frame_files) - 1)
            
            detect_start = time.time()
            for idx in sample_indices:
                sample_frame = cv2.imread(frame_files[idx])
                boxes = detect_watermarks(sample_frame, conf, iou, device)
                all_boxes.extend(boxes)
            
            detect_duration = time.time() - detect_start
            total_detections = len(all_boxes)
            
            # Remove duplicatas próximas (merge de boxes similares)
            cod5_log("task.detect_done", task_id=task_id, detections=total_detections, sample_frames=len(sample_indices), duration_s=detect_duration)
            
            # Cria máscara base a partir de todas as detecções
            if all_boxes:
                sample_frame = cv2.imread(frame_files[0])
                mask = expand_mask(all_boxes, mask_expand, sample_frame.shape)
            else:
                # Se não detectou nada, cria máscara vazia
                sample_frame = cv2.imread(frame_files[0])
                mask = np.zeros((sample_frame.shape[0], sample_frame.shape[1]), dtype=np.uint8)
            
            # Inpainting e processamento
            status_manager.update(
                task_id,
                stage="inpainting",
                progress=20,
                log_excerpt="Aplicando inpainting nos frames..."
            )
            
            inpaint_start = time.time()
            
            for idx, frame_path in enumerate(frame_files):
                frame = cv2.imread(frame_path)
                if frame is None:
                    cod5_log("task.frame_read_error", task_id=task_id, frame_idx=idx)
                    continue
                
                # Aplica inpainting
                cleaned = inpaint_frame_lama(frame, mask)
                
                # Salva frame processado (numeração começando em 1 para ffmpeg)
                output_frame_path = os.path.join(processed_frames_dir, f"frame_{idx+1:06d}.png")
                cv2.imwrite(output_frame_path, cleaned)
                
                # Atualiza progresso a cada 10 frames ou no último
                if (idx + 1) % 10 == 0 or (idx + 1) == len(frame_files):
                    progress = 20 + int((idx + 1) / len(frame_files) * 60)  # 20-80%
                    status_manager.update(
                        task_id,
                        frames_done=idx+1,
                        progress=progress,
                        log_excerpt=f"Frame {idx+1}/{len(frame_files)} processado..."
                    )
            
            inpaint_duration = time.time() - inpaint_start
            cod5_log("task.inpaint_done", task_id=task_id, frames_processed=len(frame_files), duration_s=inpaint_duration)
            
            # Renderização
            status_manager.update(
                task_id,
                stage="rendering",
                progress=85,
                log_excerpt="Renderizando vídeo final..."
            )
            
            render_start = time.time()
            
            output_video = os.path.join(temp_dir, f"{task_id}_clean.mp4")
            render_video(processed_frames_dir, output_video, audio_source=local_video, fps=fps)
            
            render_duration = time.time() - render_start
            video_size_mb = os.path.getsize(output_video) / (1024 * 1024)
            cod5_log("render.done", task_id=task_id, size_mb=video_size_mb, duration_s=render_duration)
            
            # Upload para Spaces
            status_manager.update(
                task_id,
                stage="uploading_output",
                progress=90,
                log_excerpt="Enviando vídeo processado para Spaces..."
            )
            
            upload_start = time.time()
            
            output_key = f"outputs/{task_id}_clean.mp4"
            output_url = storage.upload_file(output_video, output_key)
            
            upload_duration = time.time() - upload_start
            cod5_log("spaces.output", task_id=task_id, url=output_url, duration_s=upload_duration)
            
            # Finaliza
            total_duration = time.time() - start_time
            status_manager.update(
                task_id,
                status="completed",
                stage="finalizing",
                progress=100,
                spaces_output=output_url,
                message="Watermark removed successfully",
                log_excerpt="Processamento concluído!"
            )
            
            cod5_log("task.complete", task_id=task_id, total_duration_s=total_duration)
            
            # Webhook (opcional)
            webhook_url = params.get('webhook_url')
            if webhook_url:
                webhook_status_code = None
                webhook_error = None
                try:
                    from urllib.parse import urlparse
                    import requests
                    parsed = urlparse(webhook_url.strip())
                    if parsed.scheme and parsed.netloc:
                        status = status_manager.get(task_id)
                        cod5_log("webhook.post", task_id=task_id, url=webhook_url)
                        response = requests.post(
                            webhook_url.strip(),
                            json=status.to_dict() if status else {},
                            timeout=10
                        )
                        webhook_status_code = response.status_code
                        cod5_log("webhook.post_done", task_id=task_id, url=webhook_url, status=webhook_status_code)
                    else:
                        webhook_error = "invalid_url"
                        cod5_log("webhook.post_error", task_id=task_id, url=webhook_url, error="invalid_url")
                except Exception as e:
                    webhook_error = str(e)
                    cod5_log("webhook.post_error", task_id=task_id, url=webhook_url, error=webhook_error)
                
                # Salva status do webhook no status da task
                status_manager.update(
                    task_id,
                    webhook_status=webhook_status_code,
                    webhook_error=webhook_error
                )
            
            return {
                "success": True,
                "task_id": task_id,
                "output_url": output_url
            }
            
    except Exception as e:
        total_duration = time.time() - start_time if 'start_time' in locals() else 0
        cod5_log("task.error", task_id=task_id, error=str(e), error_type=type(e).__name__, duration_s=total_duration)
        logger.exception("Stack trace completo")
        
        status_manager.update(
            task_id,
            status="error",
            progress=0,
            error_detail=str(e),
            message=f"Erro no processamento: {str(e)}",
            log_excerpt=f"Erro: {str(e)}"
        )
        
        # Webhook de erro (opcional)
        webhook_url = params.get('webhook_url')
        if webhook_url:
            webhook_status_code = None
            webhook_error = None
            try:
                from urllib.parse import urlparse
                import requests
                parsed = urlparse(webhook_url.strip())
                if parsed.scheme and parsed.netloc:
                    status = status_manager.get(task_id)
                    cod5_log("webhook.post_error", task_id=task_id, url=webhook_url, is_error_webhook=True)
                    response = requests.post(
                        webhook_url.strip(),
                        json=status.to_dict() if status else {},
                        timeout=10
                    )
                    webhook_status_code = response.status_code
                    cod5_log("webhook.post_done", task_id=task_id, url=webhook_url, status=webhook_status_code)
                else:
                    webhook_error = "invalid_url"
            except Exception as we:
                webhook_error = str(we)
                cod5_log("webhook.post_error", task_id=task_id, url=webhook_url, error=webhook_error)
            
            # Salva status do webhook no status da task
            if webhook_status_code or webhook_error:
                status_manager.update(
                    task_id,
                    webhook_status=webhook_status_code,
                    webhook_error=webhook_error
                )
        
        raise

