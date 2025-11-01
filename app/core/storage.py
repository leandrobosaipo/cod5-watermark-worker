"""Integração com DigitalOcean Spaces (S3 API)."""
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pathlib import Path
from typing import BinaryIO, Optional, List
from datetime import datetime, timezone, timedelta
import logging

from .config import settings

logger = logging.getLogger(__name__)


class SpacesStorage:
    """Cliente para DigitalOcean Spaces."""
    
    def __init__(self):
        """Inicializa cliente S3 compatível com Spaces."""
        # Configuração para usar signature_version s3v4 (compatível com versões recentes do boto3)
        s3_config = Config(signature_version='s3v4')
        
        self.client = boto3.client(
            's3',
            endpoint_url=settings.SPACES_ENDPOINT,
            region_name=settings.SPACES_REGION,
            aws_access_key_id=settings.SPACES_KEY,
            aws_secret_access_key=settings.SPACES_SECRET,
            config=s3_config
        )
        self.bucket = settings.SPACES_BUCKET
    
    def _make_key(self, folder: str, filename: str) -> str:
        """
        Cria chave completa no Spaces aplicando prefixo de pasta.
        
        Args:
            folder: Pasta (ex: 'uploads', 'outputs')
            filename: Nome do arquivo (ex: 'task_id.mp4')
        
        Returns:
            Chave completa (ex: 'cod5-watermark-worker/uploads/task_id.mp4')
        """
        prefix = settings.SPACES_FOLDER_PREFIX
        # Remove barras duplicadas e normaliza
        key = f"{prefix}/{folder}/{filename}".replace("//", "/")
        return key.lstrip("/")
    
    def upload_file(self, file_path: str, key: str, acl: str = "public-read", use_prefix: bool = True) -> str:
        """
        Faz upload de arquivo local para Spaces.
        
        Args:
            file_path: Caminho local do arquivo
            key: Chave no Spaces (ex: uploads/task_id.mp4 ou caminho completo)
            acl: ACL (default: public-read)
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        
        Returns:
            URL pública do arquivo
        """
        import os
        import time
        
        upload_start = time.time()
        
        try:
            # Verifica tamanho do arquivo para log
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            file_size_mb = file_size / (1024 * 1024) if file_size > 0 else 0
            
            # Se key não começa com prefixo e use_prefix=True, assume formato folder/filename
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                # Detecta folder e filename da key
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    # Se não tem folder, assume uploads
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            logger.info(
                f"📤 UPLOAD_START: Iniciando upload para Spaces | "
                f"File: {os.path.basename(file_path)} | "
                f"Size: {file_size_mb:.2f}MB | "
                f"Key: {full_key} | "
                f"Bucket: {self.bucket}"
            )
            
            self.client.upload_file(
                file_path,
                self.bucket,
                full_key,
                ExtraArgs={'ACL': acl}
            )
            
            upload_duration = time.time() - upload_start
            public_url = self.public_url(full_key)
            
            logger.info(
                f"✅ UPLOAD_DONE: Upload concluído com sucesso | "
                f"Duration: {upload_duration:.2f}s | "
                f"Size: {file_size_mb:.2f}MB | "
                f"Speed: {file_size_mb / upload_duration:.2f}MB/s | "
                f"URL: {public_url} | "
                f"Key: {full_key}"
            )
            
            return public_url
            
        except ClientError as e:
            upload_duration = time.time() - upload_start
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            logger.error(
                f"❌ UPLOAD_ERROR: Erro ao fazer upload para Spaces | "
                f"Duration: {upload_duration:.2f}s | "
                f"Key: {full_key if 'full_key' in locals() else key} | "
                f"Bucket: {self.bucket} | "
                f"ErrorCode: {error_code} | "
                f"ErrorMessage: {error_msg}"
            )
            raise
        except Exception as e:
            upload_duration = time.time() - upload_start
            logger.error(
                f"❌ UPLOAD_ERROR: Erro inesperado durante upload | "
                f"Duration: {upload_duration:.2f}s | "
                f"Key: {full_key if 'full_key' in locals() else key} | "
                f"Exception: {type(e).__name__} | "
                f"Error: {str(e)}"
            )
            raise
    
    def upload_bytes(self, data: bytes, key: str, acl: str = "public-read", use_prefix: bool = True) -> str:
        """
        Faz upload de bytes para Spaces.
        
        Args:
            data: Dados binários
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            acl: ACL
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        
        Returns:
            URL pública do arquivo
        """
        try:
            # Se key não começa com prefixo e use_prefix=True, assume formato folder/filename
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            self.client.put_object(
                Bucket=self.bucket,
                Key=full_key,
                Body=data,
                ACL=acl
            )
            return self.public_url(full_key)
        except ClientError as e:
            logger.error(f"Erro ao fazer upload de bytes para Spaces: {e}")
            raise
    
    def download_file(self, key: str, local_path: str, use_prefix: bool = True) -> str:
        """
        Baixa arquivo do Spaces para caminho local.
        
        Args:
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            local_path: Caminho local de destino
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        
        Returns:
            Caminho local do arquivo
        """
        try:
            # Tenta primeiro com prefixo, se não encontrar tenta sem (compatibilidade)
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Tenta com prefixo primeiro
            try:
                self.client.download_file(self.bucket, full_key, local_path)
            except ClientError:
                # Se falhar e use_prefix=True, tenta sem prefixo (compatibilidade com arquivos antigos)
                if use_prefix and full_key != key:
                    logger.warning(f"Arquivo não encontrado com prefixo, tentando sem: {key}")
                    self.client.download_file(self.bucket, key, local_path)
                else:
                    raise
            
            return local_path
        except ClientError as e:
            logger.error(f"Erro ao baixar do Spaces: {e}")
            raise
    
    def delete_file(self, key: str, use_prefix: bool = True) -> None:
        """
        Deleta arquivo do Spaces.
        
        Args:
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        """
        try:
            # Tenta primeiro com prefixo
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            self.client.delete_object(Bucket=self.bucket, Key=full_key)
        except ClientError as e:
            # Tenta sem prefixo se falhar (compatibilidade)
            if use_prefix and full_key != key:
                try:
                    self.client.delete_object(Bucket=self.bucket, Key=key)
                except ClientError:
                    logger.error(f"Erro ao deletar do Spaces: {e}")
            else:
                logger.error(f"Erro ao deletar do Spaces: {e}")
            # Não raise para não quebrar se arquivo já não existir
    
    def public_url(self, key: str) -> str:
        """
        Gera URL pública do arquivo no Spaces.
        
        Args:
            key: Chave no Spaces
        
        Returns:
            URL pública completa
        """
        # Formato: https://bucket.region.digitaloceanspaces.com/key
        endpoint = settings.SPACES_ENDPOINT.replace("https://", "")
        return f"https://{self.bucket}.{endpoint}/{key}"
    
    def file_exists(self, key: str, use_prefix: bool = True) -> bool:
        """
        Verifica se arquivo existe no Spaces.
        
        Args:
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        
        Returns:
            True se existe, False caso contrário
        """
        try:
            # Tenta primeiro com prefixo
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            self.client.head_object(Bucket=self.bucket, Key=full_key)
            return True
        except ClientError:
            # Tenta sem prefixo se falhar (compatibilidade)
            if use_prefix and full_key != key:
                try:
                    self.client.head_object(Bucket=self.bucket, Key=key)
                    return True
                except ClientError:
                    return False
            return False
    
    def test_connection(self) -> bool:
        """Testa conexão com Spaces."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False
    
    def mark_for_expiration(self, key: str, days: int = 7, use_prefix: bool = True) -> None:
        """
        Marca arquivo para expiração adicionando metadata.
        
        Args:
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            days: Dias até expiração (default: 7)
            use_prefix: Se True, aplica prefixo de pasta automaticamente
        """
        try:
            # Resolve key com prefixo
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            # Calcula data de expiração
            expiration_date = datetime.now(timezone.utc) + timedelta(days=days)
            expiration_iso = expiration_date.isoformat()
            
            # Copia metadata existente e adiciona expires
            try:
                response = self.client.head_object(Bucket=self.bucket, Key=full_key)
                existing_metadata = response.get('Metadata', {})
            except ClientError:
                existing_metadata = {}
            
            existing_metadata['expires'] = expiration_iso
            
            # Atualiza metadata do objeto
            self.client.copy_object(
                Bucket=self.bucket,
                CopySource={'Bucket': self.bucket, 'Key': full_key},
                Key=full_key,
                Metadata=existing_metadata,
                MetadataDirective='REPLACE'
            )
            
            logger.info(f"Arquivo marcado para expiração em {days} dias | Key: {full_key} | Expira em: {expiration_iso}")
        except ClientError as e:
            logger.error(f"Erro ao marcar arquivo para expiração: {e}")
            # Não raise para não quebrar o fluxo
    
    def check_cdn_availability(self) -> dict:
        """
        Verifica disponibilidade completa do CDN.
        
        Returns:
            Dict com status do CDN:
            {
                "available": bool,
                "bucket_accessible": bool,
                "folder_active": bool,
                "error": Optional[str],
                "details": {
                    "bucket": str,
                    "folder_prefix": str,
                    "endpoint": str
                }
            }
        """
        result = {
            "available": False,
            "bucket_accessible": False,
            "folder_active": False,
            "error": None,
            "details": {
                "bucket": self.bucket,
                "folder_prefix": settings.SPACES_FOLDER_PREFIX,
                "endpoint": settings.SPACES_ENDPOINT
            }
        }
        
        try:
            # Testa conexão básica com o bucket
            self.client.head_bucket(Bucket=self.bucket)
            result["bucket_accessible"] = True
            logger.info(f"✅ CDN: Bucket '{self.bucket}' está acessível")
            
            # Verifica se a pasta/prefixo está acessível (lista objetos)
            try:
                prefix = f"{settings.SPACES_FOLDER_PREFIX}/"
                response = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,
                    MaxKeys=1
                )
                # Se consegue listar (mesmo vazio), a pasta está ativa
                result["folder_active"] = True
                logger.info(f"✅ CDN: Pasta '{prefix}' está ativa e acessível")
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == 'AccessDenied':
                    result["error"] = f"Acesso negado à pasta '{prefix}'"
                    logger.warning(f"⚠️  CDN: Acesso negado à pasta '{prefix}' | Erro: {error_code}")
                else:
                    # Pode ser que a pasta não exista ainda (normal em primeiro uso)
                    logger.info(f"ℹ️  CDN: Pasta '{prefix}' não existe ainda (será criada no primeiro upload)")
                    result["folder_active"] = True  # Assume que está OK se é primeira vez
            
            result["available"] = result["bucket_accessible"]
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            result["error"] = f"Erro ao verificar CDN: {error_code} - {error_msg}"
            logger.error(f"❌ CDN: Erro ao verificar disponibilidade | Código: {error_code} | Mensagem: {error_msg}")
        except Exception as e:
            result["error"] = f"Erro inesperado: {str(e)}"
            logger.error(f"❌ CDN: Erro inesperado ao verificar CDN | Exception: {type(e).__name__} | {str(e)}")
        
        return result
    
    def verify_upload(self, key: str, use_prefix: bool = True, timeout: int = 5) -> dict:
        """
        Verifica se o upload foi bem-sucedido e o arquivo está acessível.
        
        Args:
            key: Chave do arquivo no Spaces
            use_prefix: Se True, aplica prefixo automaticamente
            timeout: Timeout em segundos para verificação HTTP
        
        Returns:
            Dict com status da verificação:
            {
                "uploaded": bool,
                "accessible": bool,
                "url": str,
                "size": Optional[int],
                "error": Optional[str]
            }
        """
        import requests
        
        result = {
            "uploaded": False,
            "accessible": False,
            "url": None,
            "size": None,
            "error": None
        }
        
        try:
            # Resolve chave completa
            if use_prefix and not key.startswith(settings.SPACES_FOLDER_PREFIX):
                parts = key.split('/', 1)
                if len(parts) == 2:
                    folder, filename = parts
                    full_key = self._make_key(folder, filename)
                else:
                    full_key = self._make_key("uploads", parts[0])
            else:
                full_key = key
            
            # Verifica se arquivo existe no Spaces
            try:
                response = self.client.head_object(Bucket=self.bucket, Key=full_key)
                result["uploaded"] = True
                result["size"] = response.get('ContentLength')
                logger.info(f"✅ VERIFY: Arquivo existe no Spaces | Key: {full_key} | Size: {result['size']} bytes")
            except ClientError as e:
                result["error"] = f"Arquivo não encontrado no Spaces: {str(e)}"
                logger.error(f"❌ VERIFY: Arquivo não encontrado | Key: {full_key} | Erro: {str(e)}")
                return result
            
            # Gera URL pública
            public_url = self.public_url(full_key)
            result["url"] = public_url
            
            # Verifica se URL está acessível via HTTP
            try:
                http_response = requests.head(public_url, timeout=timeout, allow_redirects=True)
                if http_response.status_code == 200:
                    result["accessible"] = True
                    logger.info(f"✅ VERIFY: URL pública está acessível | URL: {public_url} | Status: {http_response.status_code}")
                else:
                    result["error"] = f"URL retornou status {http_response.status_code}"
                    logger.warning(f"⚠️  VERIFY: URL retornou status inesperado | URL: {public_url} | Status: {http_response.status_code}")
            except requests.RequestException as e:
                result["error"] = f"Erro ao verificar URL: {str(e)}"
                logger.warning(f"⚠️  VERIFY: Erro ao verificar URL pública | URL: {public_url} | Erro: {str(e)}")
            
        except Exception as e:
            result["error"] = f"Erro inesperado: {str(e)}"
            logger.error(f"❌ VERIFY: Erro inesperado | Exception: {type(e).__name__} | {str(e)}")
        
        return result
    
    def cleanup_expired_files(self) -> List[str]:
        """
        Remove arquivos expirados do Spaces.
        
        Returns:
            Lista de keys de arquivos deletados
        """
        deleted_keys = []
        prefix = f"{settings.SPACES_FOLDER_PREFIX}/"
        
        try:
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            
            now = datetime.now(timezone.utc)
            
            for page in pages:
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    
                    try:
                        # Obtém metadata do objeto
                        response = self.client.head_object(Bucket=self.bucket, Key=key)
                        metadata = response.get('Metadata', {})
                        
                        if 'expires' in metadata:
                            expires_str = metadata['expires']
                            try:
                                expires_date = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                                
                                # Se expirou, deleta
                                if expires_date < now:
                                    self.client.delete_object(Bucket=self.bucket, Key=key)
                                    deleted_keys.append(key)
                                    logger.info(f"Arquivo expirado deletado | Key: {key} | Expirava em: {expires_str}")
                            except (ValueError, AttributeError) as e:
                                logger.warning(f"Erro ao parsear data de expiração para {key}: {e}")
                    except ClientError as e:
                        logger.warning(f"Erro ao verificar expiração de {key}: {e}")
            
            if deleted_keys:
                logger.info(f"Limpeza concluída: {len(deleted_keys)} arquivos expirados removidos")
            else:
                logger.debug("Nenhum arquivo expirado encontrado para remoção")
                
        except ClientError as e:
            logger.error(f"Erro ao limpar arquivos expirados: {e}")
        
        return deleted_keys


# Instância global
storage = SpacesStorage()

