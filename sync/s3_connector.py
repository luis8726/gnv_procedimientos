"""
s3_connector.py — Interacción con AWS S3.

Provee:
  - list_pdfs()     → lista de {key, etag, filename} de todos los PDFs en el bucket/prefix
  - download_pdf()  → descarga un PDF a un archivo temporal y retorna su path
"""

import os
import tempfile
from typing import Generator

import boto3
from botocore.exceptions import ClientError


def _get_client():
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def list_pdfs() -> list[dict]:
    """
    Retorna lista de dicts con info de cada PDF en el bucket:
    [{"key": "docs/manual.pdf", "etag": "abc123", "filename": "manual.pdf"}, ...]
    """
    client = _get_client()
    bucket = os.getenv("S3_BUCKET_NAME")
    prefix = os.getenv("S3_PREFIX", "")

    paginator = client.get_paginator("list_objects_v2")
    results = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Filtrar solo PDFs (ignorar "carpetas" y otros archivos)
            if not key.lower().endswith(".pdf"):
                continue
            etag = obj["ETag"].strip('"')  # S3 devuelve el ETag entre comillas
            filename = key.split("/")[-1]  # Solo el nombre del archivo
            results.append({"key": key, "etag": etag, "filename": filename})

    return results


def download_pdf(s3_key: str) -> str:
    """
    Descarga el PDF desde S3 a un archivo temporal.
    Retorna el path del archivo temporal.
    El llamador es responsable de eliminar el archivo después de usarlo.
    """
    client = _get_client()
    bucket = os.getenv("S3_BUCKET_NAME")
    filename = s3_key.split("/")[-1]

    # Crear archivo temporal que no se borra automáticamente (delete=False)
    tmp = tempfile.NamedTemporaryFile(
        suffix=f"_{filename}",
        delete=False,
        prefix="pdf_sync_"
    )
    tmp.close()

    client.download_file(bucket, s3_key, tmp.name)
    return tmp.name


def bucket_exists() -> bool:
    """Valida que el bucket sea accesible con las credenciales configuradas."""
    try:
        client = _get_client()
        client.head_bucket(Bucket=os.getenv("S3_BUCKET_NAME"))
        return True
    except ClientError:
        return False
