"""
state.py — Persistencia del estado de sincronización.

En local: usa sync_state.json
En Render/producción: el vector_store_id viene de la variable de entorno
OPENAI_VECTOR_STORE_ID, y el estado de sync se guarda igual en JSON
(cada servicio tiene su propia copia, lo cual es aceptable porque
el worker es el único que escribe y la app solo lee el VS ID).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "sync_state.json"


def _load() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "vector_store_id": None,
        "sync_status": {
            "is_syncing": False,
            "current_file": None,
            "last_sync": None,
            "last_result": None,
        },
        "files": {},
    }


def _save(state: dict):
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ── Vector Store ──────────────────────────────────────────────────────────────

def get_vector_store_id() -> str | None:
    # Prioridad 1: variable de entorno (Render / producción)
    env_vs_id = os.getenv("OPENAI_VECTOR_STORE_ID", "").strip()
    if env_vs_id:
        return env_vs_id
    # Prioridad 2: state.json (local)
    return _load().get("vector_store_id")


def set_vector_store_id(vs_id: str):
    state = _load()
    state["vector_store_id"] = vs_id
    _save(state)


# ── Archivos trackeados ───────────────────────────────────────────────────────

def get_tracked_files() -> dict:
    return _load().get("files", {})


def upsert_file(s3_key: str, etag: str, openai_file_id: str, filename: str):
    state = _load()
    state["files"][s3_key] = {
        "etag": etag,
        "openai_file_id": openai_file_id,
        "filename": filename,
        "last_synced": datetime.now(timezone.utc).isoformat(),
    }
    _save(state)


def remove_file(s3_key: str):
    state = _load()
    state["files"].pop(s3_key, None)
    _save(state)


# ── Sync status ───────────────────────────────────────────────────────────────

def set_syncing(is_syncing: bool, current_file: str | None = None):
    state = _load()
    state.setdefault("sync_status", {})
    state["sync_status"]["is_syncing"] = is_syncing
    state["sync_status"]["current_file"] = current_file
    if not is_syncing:
        state["sync_status"]["last_sync"] = datetime.now(timezone.utc).isoformat()
    _save(state)


def set_last_result(result_dict: dict):
    state = _load()
    state.setdefault("sync_status", {})
    state["sync_status"]["last_result"] = result_dict
    _save(state)


def get_sync_status() -> dict:
    return _load().get("sync_status", {
        "is_syncing": False,
        "current_file": None,
        "last_sync": None,
        "last_result": None,
    })


def get_last_sync_time() -> str | None:
    return get_sync_status().get("last_sync")
