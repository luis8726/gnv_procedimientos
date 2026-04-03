"""
app.py — Streamlit MVP.

Esta app NO maneja sincronización. Solo:
  - Lee sync_state.json (escrito por worker.py)
  - Muestra un aviso sutil si hay un sync en curso
  - Permite chatear con el Vector Store

Para correr:
    streamlit run app.py

El worker debe estar corriendo en paralelo:
    python worker.py
"""

import os
import time

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

APP_TITLE = os.getenv("APP_TITLE", "Base de Conocimiento")

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

from sync.state import get_tracked_files, get_sync_status, get_vector_store_id
from chat.chat_engine import chat

# ── Estilos ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

    .stApp { background: #0f0f13; color: #e8e6e0; }

    [data-testid="stSidebar"] {
        background: #16161d !important;
        border-right: 1px solid #2a2a35;
    }

    .app-header {
        font-family: 'DM Serif Display', serif;
        font-size: 2rem;
        color: #f0ede6;
        letter-spacing: -0.02em;
        margin-bottom: 0.2rem;
    }
    .app-subtitle {
        font-size: 0.85rem;
        color: #6b6b7a;
        font-weight: 300;
        margin-bottom: 1.5rem;
    }

    /* ── Banner de sync en curso ── */
    .sync-banner {
        background: #1a1f2e;
        border: 1px solid #2a3a5a;
        border-left: 3px solid #4a9eff;
        border-radius: 8px;
        padding: 8px 14px;
        margin-bottom: 12px;
        font-size: 0.82rem;
        color: #7ab8ff;
        display: flex;
        align-items: center;
        gap: 8px;
        animation: pulse-border 2s ease-in-out infinite;
    }
    @keyframes pulse-border {
        0%, 100% { border-left-color: #4a9eff; }
        50%       { border-left-color: #7ab8ff; }
    }

    .file-item {
        background: #1e1e28;
        border: 1px solid #2a2a38;
        border-radius: 8px;
        padding: 8px 12px;
        margin: 4px 0;
        font-size: 0.8rem;
        color: #a8a6b0;
    }
    .file-item-name { color: #d8d6d0; font-weight: 500; font-size: 0.82rem; }

    .stTextInput input, .stTextArea textarea {
        background: #1a1a23 !important;
        border: 1px solid #2a2a38 !important;
        color: #e8e6e0 !important;
        border-radius: 8px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #7c6af7 !important;
        box-shadow: 0 0 0 2px rgba(124,106,247,0.15) !important;
    }

    .stButton button {
        background: #7c6af7 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }
    .stButton button:hover {
        background: #9080ff !important;
        box-shadow: 0 4px 12px rgba(124,106,247,0.3) !important;
    }

    [data-testid="metric-container"] {
        background: #1a1a23;
        border: 1px solid #23232f;
        border-radius: 10px;
        padding: 12px;
    }

    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "conversation" not in st.session_state:
    st.session_state.conversation = []

# ── Auto-refresh cuando hay sync en curso ────────────────────────────────────
# Streamlit re-ejecuta el script cada vez que el usuario interactúa.
# Cuando hay un sync activo, agregamos un rerun periódico para actualizar el banner.
sync_status = get_sync_status()
if sync_status.get("is_syncing"):
    time.sleep(2)
    st.rerun()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div style="margin-bottom:1.5rem;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.4rem; color:#f0ede6; margin-bottom:2px;">
            📚 {APP_TITLE}
        </div>
        <div style="font-size:0.75rem; color:#5a5a6a; font-weight:300;">
            Powered by OpenAI · AWS S3
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Estado del VS ──
    st.markdown("**Vector Store**")
    vs_id = get_vector_store_id()
    if vs_id:
        st.markdown('<span style="color:#4ade80; font-size:0.8rem;">● Activo</span>', unsafe_allow_html=True)
        st.code(vs_id[:24] + "...", language=None)
    else:
        st.markdown('<span style="color:#fb923c; font-size:0.8rem;">● Sin inicializar</span>', unsafe_allow_html=True)
        st.caption("Iniciá el worker para crear el Vector Store.")

    st.markdown("---")

    # ── Documentos indexados ──
    tracked = get_tracked_files()
    st.markdown(f"**Documentos indexados** ({len(tracked)})")

    if tracked:
        for key, info in tracked.items():
            st.markdown(f"""
            <div class="file-item">
                <div class="file-item-name">📄 {info['filename']}</div>
                <div style="font-size:0.72rem; color:#555566; margin-top:2px;">
                    Sync: {info.get('last_synced','')[:10]}
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("Sin documentos indexados. El worker sincronizará automáticamente.")

    st.markdown("---")

    # ── Estado del último sync ──
    last_result = sync_status.get("last_result")
    if last_result:
        added   = len(last_result.get("added", []))
        updated = len(last_result.get("updated", []))
        deleted = len(last_result.get("deleted", []))
        errors  = len(last_result.get("errors", []))
        ts      = last_result.get("timestamp", "")[:16].replace("T", " ")

        st.markdown("**Última sincronización**")
        st.caption(f"{ts} UTC")
        cols = st.columns(3)
        cols[0].metric("➕", added)
        cols[1].metric("🔄", updated)
        cols[2].metric("🗑️", deleted)
        if errors:
            st.warning(f"{errors} error(es) en el último sync")

    st.markdown("---")

    # ── Limpiar chat ──
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.conversation = []
        st.rerun()


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="app-header">{APP_TITLE}</div>
<div class="app-subtitle">Consultá los documentos técnicos en lenguaje natural</div>
""", unsafe_allow_html=True)

# ── Banner sutil de sync en curso ─────────────────────────────────────────────
if sync_status.get("is_syncing"):
    current_file = sync_status.get("current_file", "documentos")
    st.markdown(f"""
    <div class="sync-banner">
        <span>⟳</span>
        <span>Actualizando base de conocimiento: <strong>{current_file}</strong> — podés seguir consultando normalmente.</span>
    </div>
    """, unsafe_allow_html=True)

# ── Métricas ──────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Documentos", len(get_tracked_files()))
with col2:
    st.metric("Vector Store", "Activo" if get_vector_store_id() else "Inactivo")
with col3:
    st.metric("Mensajes", len(st.session_state.conversation) // 2)

st.markdown("---")

# ── Historial de chat ─────────────────────────────────────────────────────────
if not st.session_state.conversation:
    st.markdown("""
    <div style="text-align:center; padding:3rem 1rem; color:#3a3a4a;">
        <div style="font-size:2.5rem; margin-bottom:1rem;">💬</div>
        <div style="font-size:1rem; color:#5a5a6a;">Hacé tu primera pregunta sobre los documentos</div>
        <div style="font-size:0.8rem; color:#3a3a4a; margin-top:0.5rem;">
            Los documentos se sincronizan automáticamente desde S3
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    for msg in st.session_state.conversation:
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.write(msg["content"])
        elif msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(msg["content"])

# ── Input ─────────────────────────────────────────────────────────────────────
if not get_vector_store_id():
    st.info("⏳ El worker aún no inicializó el Vector Store. Iniciá `python worker.py` y esperá el sync inicial.")
else:
    user_input = st.chat_input("Escribí tu pregunta sobre los documentos...")

    if user_input and user_input.strip():
        with st.chat_message("user", avatar="👤"):
            st.write(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            with st.spinner("Buscando en los documentos..."):
                try:
                    response_text, updated_history = chat(
                        user_message=user_input,
                        conversation_history=st.session_state.conversation,
                    )
                    st.session_state.conversation = updated_history
                    st.markdown(response_text)
                except Exception as e:
                    st.error(f"Error al consultar: {e}")

        st.rerun()
