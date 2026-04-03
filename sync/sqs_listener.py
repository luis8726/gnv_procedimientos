"""
sqs_listener.py — Escucha eventos de S3 via SQS y dispara la sincronización.

Cómo funciona:
  1. S3 emite un evento (PUT/DELETE) → lo envía a SQS automáticamente
  2. Este worker hace long-polling a SQS (espera hasta 20s por mensaje)
  3. Al recibir un mensaje, extrae el evento de S3 y llama a sync_engine
  4. Elimina el mensaje de la cola (acknowledge)
  5. Repite indefinidamente

Para correr:
    python worker.py

Configuración AWS requerida (ver README):
  - Cola SQS configurada para recibir eventos del bucket S3
  - Variable de entorno SQS_QUEUE_URL
"""

import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

from sync.sync_engine import process_s3_event

logger = logging.getLogger(__name__)


def _get_sqs_client():
    return boto3.client(
        "sqs",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def _parse_s3_event(body: dict) -> list[dict]:
    """
    Extrae los eventos de S3 del mensaje SQS.
    Soporta mensajes directos de S3 y mensajes envueltos en SNS.

    Retorna lista de: {"event_name": str, "s3_key": str, "etag": str|None}
    """
    events = []

    # Si el mensaje viene envuelto en SNS (S3 → SNS → SQS)
    if body.get("Type") == "Notification" and "Message" in body:
        body = json.loads(body["Message"])

    # Mensaje directo de S3
    records = body.get("Records", [])
    for record in records:
        event_source = record.get("eventSource", "")
        event_name = record.get("eventName", "")

        if event_source != "aws:s3":
            continue

        s3_info = record.get("s3", {})
        s3_key = s3_info.get("object", {}).get("key", "")
        # S3 urlencodea las claves con espacios y caracteres especiales
        s3_key = s3_key.replace("+", " ")

        etag = s3_info.get("object", {}).get("eTag", "").strip('"') or None

        if s3_key:
            events.append({
                "event_name": event_name,
                "s3_key": s3_key,
                "etag": etag,
            })

    return events


def listen(max_messages: int = 10, wait_seconds: int = 20):
    """
    Loop principal de long-polling a SQS.
    Corre indefinidamente hasta que el proceso sea interrumpido (Ctrl+C / SIGTERM).

    Args:
        max_messages:  máximo de mensajes a recibir por poll (1-10)
        wait_seconds:  segundos de long-polling (máx 20, recomendado 20)
    """
    sqs = _get_sqs_client()
    queue_url = os.getenv("SQS_QUEUE_URL", "").strip()

    if not queue_url:
        raise ValueError("SQS_QUEUE_URL no está configurada en las variables de entorno.")

    logger.info(f"Worker iniciado. Escuchando cola: {queue_url}")
    logger.info("Presioná Ctrl+C para detener.")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_seconds,          # Long polling
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )

            messages = response.get("Messages", [])

            if not messages:
                # Sin mensajes — el long-polling ya esperó 20s, volver a intentar
                continue

            for message in messages:
                receipt_handle = message["ReceiptHandle"]
                message_id = message["MessageId"]

                try:
                    body = json.loads(message["Body"])
                    s3_events = _parse_s3_event(body)

                    if not s3_events:
                        logger.debug(f"Mensaje {message_id} sin eventos de S3, ignorando.")
                    else:
                        for evt in s3_events:
                            logger.info(
                                f"Evento recibido: {evt['event_name']} → {evt['s3_key']}"
                            )
                            process_s3_event(
                                event_name=evt["event_name"],
                                s3_key=evt["s3_key"],
                                etag=evt["etag"],
                            )

                    # Eliminar el mensaje de la cola (ACK)
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=receipt_handle,
                    )

                except json.JSONDecodeError as e:
                    logger.error(f"Mensaje {message_id} con JSON inválido: {e}")
                    # Eliminar igual para no quedar en loop con mensajes corruptos
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

                except Exception as e:
                    logger.error(
                        f"Error procesando mensaje {message_id}: {e}",
                        exc_info=True,
                    )
                    # No eliminar: SQS reintentará después del visibility timeout

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("AWS.SimpleQueueService.NonExistentQueue",):
                logger.error(f"Cola SQS no encontrada: {queue_url}")
                raise
            logger.warning(f"Error de SQS ({error_code}), reintentando en 5s...")
            time.sleep(5)

        except KeyboardInterrupt:
            logger.info("Worker detenido por el usuario.")
            break

        except Exception as e:
            logger.error(f"Error inesperado en el loop: {e}", exc_info=True)
            time.sleep(5)
