"""Integração com DigitalOcean Spaces (S3 API)."""
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
from typing import BinaryIO, Optional
import logging

from .config import settings

logger = logging.getLogger(__name__)


class SpacesStorage:
    """Cliente para DigitalOcean Spaces."""
    
    def __init__(self):
        """Inicializa cliente S3 compatível com Spaces."""
        self.client = boto3.client(
            's3',
            endpoint_url=settings.SPACES_ENDPOINT,
            region_name=settings.SPACES_REGION,
            aws_access_key_id=settings.SPACES_KEY,
            aws_secret_access_key=settings.SPACES_SECRET,
            signature_version='s3v4'
        )
        self.bucket = settings.SPACES_BUCKET
    
    def upload_file(self, file_path: str, key: str, acl: str = "public-read") -> str:
        """
        Faz upload de arquivo local para Spaces.
        
        Args:
            file_path: Caminho local do arquivo
            key: Chave no Spaces (ex: uploads/task_id.mp4)
            acl: ACL (default: public-read)
        
        Returns:
            URL pública do arquivo
        """
        try:
            self.client.upload_file(
                file_path,
                self.bucket,
                key,
                ExtraArgs={'ACL': acl}
            )
            return self.public_url(key)
        except ClientError as e:
            logger.error(f"Erro ao fazer upload para Spaces: {e}")
            raise
    
    def upload_bytes(self, data: bytes, key: str, acl: str = "public-read") -> str:
        """
        Faz upload de bytes para Spaces.
        
        Args:
            data: Dados binários
            key: Chave no Spaces
            acl: ACL
        
        Returns:
            URL pública do arquivo
        """
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ACL=acl
            )
            return self.public_url(key)
        except ClientError as e:
            logger.error(f"Erro ao fazer upload de bytes para Spaces: {e}")
            raise
    
    def download_file(self, key: str, local_path: str) -> str:
        """
        Baixa arquivo do Spaces para caminho local.
        
        Args:
            key: Chave no Spaces
            local_path: Caminho local de destino
        
        Returns:
            Caminho local do arquivo
        """
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, key, local_path)
            return local_path
        except ClientError as e:
            logger.error(f"Erro ao baixar do Spaces: {e}")
            raise
    
    def delete_file(self, key: str) -> None:
        """
        Deleta arquivo do Spaces.
        
        Args:
            key: Chave no Spaces
        """
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
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
    
    def file_exists(self, key: str) -> bool:
        """
        Verifica se arquivo existe no Spaces.
        
        Args:
            key: Chave no Spaces
        
        Returns:
            True se existe, False caso contrário
        """
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False
    
    def test_connection(self) -> bool:
        """Testa conexão com Spaces."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False


# Instância global
storage = SpacesStorage()

