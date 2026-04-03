"""
vs_manager.py — Compatible con openai >= 2.0
"""

import os
from openai import OpenAI
from sync.state import get_vector_store_id, set_vector_store_id


def get_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_or_create_vector_store() -> str:
    client = get_client()

    env_vs_id = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()
    if env_vs_id:
        return env_vs_id

    saved_vs_id = get_vector_store_id()
    if saved_vs_id:
        try:
            client.vector_stores.retrieve(saved_vs_id)
            return saved_vs_id
        except Exception:
            pass

    app_title = os.getenv("APP_TITLE", "Base de Conocimiento")
    vs = client.vector_stores.create(name=f"{app_title} — PDFs")
    set_vector_store_id(vs.id)
    return vs.id


def upload_pdf_to_vs(vs_id: str, local_path: str, filename: str) -> str:
    client = get_client()

    with open(local_path, "rb") as f:
        file_batch = client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vs_id,
            files=[(filename, f, "application/pdf")],
        )

    files_in_vs = list(client.vector_stores.files.list(vector_store_id=vs_id))

    for vs_file in files_in_vs:
        try:
            oai_file = client.files.retrieve(vs_file.id)
            if oai_file.filename == filename:
                return vs_file.id
        except Exception:
            continue

    batch_files = list(
        client.vector_stores.file_batches.list_files(
            vector_store_id=vs_id,
            batch_id=file_batch.id,
        )
    )
    if batch_files:
        return batch_files[0].id

    raise ValueError(f"No se pudo obtener el file_id para {filename}")


def delete_file_from_vs(vs_id: str, openai_file_id: str):
    client = get_client()
    try:
        client.vector_stores.files.delete(
            vector_store_id=vs_id,
            file_id=openai_file_id,
        )
        client.files.delete(openai_file_id)
    except Exception as e:
        print(f"  warning: Error al eliminar {openai_file_id}: {e}")


def get_vs_info(vs_id: str) -> dict:
    client = get_client()
    try:
        vs = client.vector_stores.retrieve(vs_id)
        files = list(client.vector_stores.files.list(vector_store_id=vs_id))
        return {
            "id": vs.id,
            "name": vs.name,
            "file_count": vs.file_counts.completed,
            "status": vs.status,
            "files": [{"id": f.id, "status": f.status} for f in files],
        }
    except Exception as e:
        return {"error": str(e)}
