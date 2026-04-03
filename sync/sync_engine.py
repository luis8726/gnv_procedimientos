"""
sync_engine.py — Procesa eventos individuales de S3.

A diferencia de la v1 (que escaneaba todo el bucket), esta versión
procesa UN evento a la vez: el que SQS le entrega.

Eventos soportados:
  - ObjectCreated (PUT, COPY, POST, multipart) → agregar o actualizar en VS
  - ObjectRemoved (DELETE)                     → eliminar del VS

También expone run_initial_sync() para el primer arranque, que sí
escanea el bucket completo para inicializar el estado.
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sync.s3_connector import list_pdfs, download_pdf
from sync.state import (
    get_tracked_files,
    upsert_file,
    remove_file,
    set_syncing,
    set_last_result,
)
from vectorstore.vs_manager import (
    get_or_create_vector_store,
    upload_pdf_to_vs,
    delete_file_from_vs,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    vector_store_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.updated) + len(self.deleted)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "errors": self.errors,
            "vector_store_id": self.vector_store_id,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"✅ {len(self.added)} agregado(s): {', '.join(self.added)}")
        if self.updated:
            parts.append(f"🔄 {len(self.updated)} actualizado(s): {', '.join(self.updated)}")
        if self.deleted:
            parts.append(f"🗑️ {len(self.deleted)} eliminado(s): {', '.join(self.deleted)}")
        if self.errors:
            parts.append(f"❌ {len(self.errors)} error(es)")
        if not parts:
            parts.append("✓ Sin cambios")
        return " · ".join(parts)


def process_s3_event(event_name: str, s3_key: str, etag: str | None = None) -> SyncResult:
    """
    Procesa un evento individual de S3 recibido desde SQS.

    Args:
        event_name: ej. "ObjectCreated:Put", "ObjectRemoved:Delete"
        s3_key:     clave del objeto en S3 (ej. "docs/manual.pdf")
        etag:       ETag del objeto (solo para eventos Created)
    """
    result = SyncResult()

    # Solo procesar PDFs
    if not s3_key.lower().endswith(".pdf"):
        logger.info(f"Ignorando evento para archivo no-PDF: {s3_key}")
        return result

    prefix = os.getenv("S3_PREFIX", "")
    if prefix and not s3_key.startswith(prefix):
        logger.info(f"Ignorando archivo fuera del prefix configurado: {s3_key}")
        return result

    filename = s3_key.split("/")[-1]

    try:
        vs_id = get_or_create_vector_store()
        result.vector_store_id = vs_id
        tracked = get_tracked_files()

        # ── EVENTO: archivo creado o modificado ──────────────────────────────
        if event_name.startswith("ObjectCreated"):
            is_update = s3_key in tracked

            # Si el ETag no cambió, no hay nada que hacer (evento duplicado)
            if is_update and etag and tracked[s3_key]["etag"] == etag:
                logger.info(f"ETag sin cambios para {filename}, ignorando.")
                return result

            action = "Actualizando" if is_update else "Agregando"
            logger.info(f"{action} {filename} en el Vector Store...")
            set_syncing(True, filename)

            local_path = download_pdf(s3_key)
            new_file_id = upload_pdf_to_vs(vs_id, local_path, filename)
            os.unlink(local_path)

            # Si es actualización, borrar el archivo viejo DESPUÉS de subir el nuevo
            if is_update:
                old_file_id = tracked[s3_key]["openai_file_id"]
                delete_file_from_vs(vs_id, old_file_id)
                result.updated.append(filename)
            else:
                result.added.append(filename)

            upsert_file(s3_key, etag or "", new_file_id, filename)

        # ── EVENTO: archivo eliminado ─────────────────────────────────────────
        elif event_name.startswith("ObjectRemoved"):
            if s3_key not in tracked:
                logger.info(f"Archivo no trackeado, nada que eliminar: {s3_key}")
                return result

            logger.info(f"Eliminando {filename} del Vector Store...")
            set_syncing(True, filename)

            old_file_id = tracked[s3_key]["openai_file_id"]
            delete_file_from_vs(vs_id, old_file_id)
            remove_file(s3_key)
            result.deleted.append(filename)

        else:
            logger.info(f"Evento no manejado: {event_name}")

    except Exception as e:
        msg = f"Error procesando {filename}: {e}"
        logger.error(msg, exc_info=True)
        result.errors.append(msg)
    finally:
        set_syncing(False)
        set_last_result(result.to_dict())

    logger.info(f"Sync completado: {result.summary()}")
    return result


def run_initial_sync() -> SyncResult:
    """
    Sincronización completa del bucket. Se ejecuta UNA SOLA VEZ al arrancar
    el worker por primera vez, para asegurarse de que el VS está al día
    con lo que hay en S3 antes de empezar a escuchar eventos.
    """
    result = SyncResult()
    logger.info("Iniciando sincronización inicial completa del bucket...")

    try:
        set_syncing(True, "Sincronización inicial")
        vs_id = get_or_create_vector_store()
        result.vector_store_id = vs_id

        s3_files = list_pdfs()
        tracked = get_tracked_files()
        s3_keys = {f["key"] for f in s3_files}

        files_to_add = [f for f in s3_files if f["key"] not in tracked]
        files_to_update = [
            f for f in s3_files
            if f["key"] in tracked and tracked[f["key"]]["etag"] != f["etag"]
        ]
        keys_to_delete = set(tracked.keys()) - s3_keys

        for s3_file in files_to_add + files_to_update:
            key, etag, filename = s3_file["key"], s3_file["etag"], s3_file["filename"]
            is_update = key in tracked
            set_syncing(True, filename)
            try:
                local_path = download_pdf(key)
                new_file_id = upload_pdf_to_vs(vs_id, local_path, filename)
                os.unlink(local_path)
                if is_update:
                    delete_file_from_vs(vs_id, tracked[key]["openai_file_id"])
                    result.updated.append(filename)
                else:
                    result.added.append(filename)
                upsert_file(key, etag, new_file_id, filename)
            except Exception as e:
                result.errors.append(f"Error con '{filename}': {e}")

        for key in keys_to_delete:
            filename = tracked[key]["filename"]
            set_syncing(True, filename)
            try:
                delete_file_from_vs(vs_id, tracked[key]["openai_file_id"])
                remove_file(key)
                result.deleted.append(filename)
            except Exception as e:
                result.errors.append(f"Error eliminando '{filename}': {e}")

    except Exception as e:
        result.errors.append(f"Error en sync inicial: {e}")
    finally:
        set_syncing(False)
        set_last_result(result.to_dict())

    logger.info(f"Sync inicial completado: {result.summary()}")
    return result
