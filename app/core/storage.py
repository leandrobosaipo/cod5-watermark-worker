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
        try:
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
            
            self.client.upload_file(
                file_path,
                self.bucket,
                full_key,
                ExtraArgs={'ACL': acl}
            )
            return self.public_url(full_key)
        except ClientError as e:
            logger.error(f"Erro ao fazer upload para Spaces: {e}")
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

