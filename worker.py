"""
worker.py — Punto de entrada del worker de sincronización.

Este proceso corre INDEPENDIENTE de Streamlit.
Se encarga de:
  1. Sincronización inicial al arrancar (por si algo cambió mientras estaba caído)
  2. Escuchar eventos de S3 via SQS indefinidamente

Para correr:
    python worker.py

En producción (Docker, systemd, etc.):
    # Dockerfile ejemplo
    CMD ["python", "worker.py"]
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("worker")

# ── Validar variables de entorno requeridas ───────────────────────────────────
REQUIRED_VARS = [
    "OPENAI_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "S3_BUCKET_NAME",
    "SQS_QUEUE_URL",
]

missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    logger.error(f"Faltan variables de entorno requeridas: {', '.join(missing)}")
    logger.error("Copiá .env.example a .env y completá los valores.")
    sys.exit(1)

# ── Importar módulos del proyecto ─────────────────────────────────────────────
from sync.sync_engine import run_initial_sync
from sync.sqs_listener import listen


def main():
    logger.info("=" * 60)
    logger.info("  PDF Sync Worker — arrancando")
    logger.info("=" * 60)

    # ── Paso 1: sincronización inicial ────────────────────────────────────────
    # Garantiza que el VS está al día antes de empezar a escuchar eventos.
    # Útil cuando el worker estuvo caído y se perdieron eventos en la cola.
    logger.info("Paso 1/2: Sincronización inicial del bucket...")
    result = run_initial_sync()

    if result.errors:
        logger.warning(f"Sync inicial completado con errores: {result.errors}")
    else:
        logger.info(f"Sync inicial OK: {result.summary()}")

    # ── Paso 2: escuchar eventos SQS ──────────────────────────────────────────
    logger.info("Paso 2/2: Iniciando listener de eventos SQS...")
    listen()


if __name__ == "__main__":
    main()
