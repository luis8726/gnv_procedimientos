"""
app.py — Streamlit MVP con worker SQS en background thread.
UptimeRobot hace ping cada 5 min para mantener Render activo.
"""

import os
import threading
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

from sync.state import get_sync_status, get_vector_store_id
from chat.chat_engine import chat
from vectorstore.vs_manager import get_client

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    .stApp { background: #0f0f13; color: #e8e6e0; }
    [data-testid="stSidebar"] { background: #16161d !important; border-right: 1px solid #2a2a35; }
    .app-header { font-family: 'DM Serif Display', serif; font-size: 2rem; color: #f0ede6; letter-spacing: -0.02em; margin-bottom: 0.2rem; }
    .app-subtitle { font-size: 0.85rem; color: #6b6b7a; font-weight: 300; margin-bottom: 1.5rem; }
    .sync-banner { background: #1a1f2e; border: 1px solid #2a3a5a; border-left: 3px solid #4a9eff; border-radius: 8px; padding: 8px 14px; margin-bottom: 12px; font-size: 0.82rem; color: #7ab8ff; }
    .file-item { background: #1e1e28; border: 1px solid #2a2a38; border-radius: 8px; padding: 8px 12px; margin: 4px 0; font-size: 0.8rem; color: #a8a6b0; }
    .file-item-name { color: #d8d6d0; font-weight: 500; font-size: 0.82rem; }
    [data-testid="metric-container"] { background: #1a1a23; border: 1px solid #23232f; border-radius: 10px; padding: 12px; }
    .stButton button { background: #7c6af7 !important; color: white !important; border: none !important; border-radius: 8px !important; font-weight: 500 !important; }
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)


# ── Worker en background thread — arranca una sola vez por proceso ────────────
def _start_worker():
    if st.session_state.get("worker_started"):
        return
    st.session_state["worker_started"] = True

    def run():
        try:
            from sync.sync_engine import run_initial_sync
            run_initial_sync()
        except Exception as e:
            print(f"[worker] Error en sync inicial: {e}")
        try:
            from sync.sqs_listener import listen
            listen()
        except Exception as e:
            print(f"[worker] Error en listener SQS: {e}")

    t = threading.Thread(target=run, daemon=True, name="sqs-worker")
    t.start()

_start_worker()


@st.cache_data(ttl=60)
def get_vs_files():
    try:
        vs_id = get_vector_store_id()
        if not vs_id:
            return []
        client = get_client()
        files = list(client.vector_stores.files.list(vector_store_id=vs_id))
        result = []
        for f in files:
            if f.status == "completed":
                try:
                    oai_file = client.files.retrieve(f.id)
                    result.append(oai_file.filename)
                except:
                    result.append(f.id)
        return result
    except:
        return []


if "conversation" not in st.session_state:
    st.session_state.conversation = []

sync_status = get_sync_status()
if sync_status.get("is_syncing"):
    time.sleep(2)
    st.rerun()

vs_id = get_vector_store_id()
vs_files = get_vs_files()

with st.sidebar:
    st.markdown(f"""
    <div style="margin-bottom:1.5rem;">
        <div style="font-family:'DM Serif Display',serif; font-size:1.4rem; color:#f0ede6; margin-bottom:2px;">📚 {APP_TITLE}</div>
        <div style="font-size:0.75rem; color:#5a5a6a; font-weight:300;">Powered by OpenAI · AWS S3</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Vector Store**")
    if vs_id:
        st.markdown('<span style="color:#4ade80; font-size:0.8rem;">● Activo</span>', unsafe_allow_html=True)
        st.code(vs_id[:24] + "...", language=None)
    else:
        st.markdown('<span style="color:#fb923c; font-size:0.8rem;">● Inicializando...</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"**Documentos indexados** ({len(vs_files)})")
    if vs_files:
        for filename in vs_files:
            st.markdown(f'<div class="file-item"><div class="file-item-name">📄 {filename}</div></div>', unsafe_allow_html=True)
    else:
        st.caption("Cargando documentos...")

    st.markdown("---")
    last_result = sync_status.get("last_result")
    if last_result:
        ts = last_result.get("timestamp", "")[:16].replace("T", " ")
        st.markdown("**Última sincronización**")
        st.caption(f"{ts} UTC")
        cols = st.columns(3)
        cols[0].metric("➕", len(last_result.get("added", [])))
        cols[1].metric("🔄", len(last_result.get("updated", [])))
        cols[2].metric("🗑️", len(last_result.get("deleted", [])))

    st.markdown("---")
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.conversation = []
        st.rerun()

st.markdown(f"""
<div class="app-header">{APP_TITLE}</div>
<div class="app-subtitle">Consultá los documentos técnicos en lenguaje natural</div>
""", unsafe_allow_html=True)

if sync_status.get("is_syncing"):
    st.markdown(f'<div class="sync-banner">⟳ Actualizando: <strong>{sync_status.get("current_file","")}</strong> — podés seguir consultando.</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1: st.metric("Documentos", len(vs_files))
with col2: st.metric("Vector Store", "Activo" if vs_id else "Iniciando...")
with col3: st.metric("Mensajes", len(st.session_state.conversation) // 2)

st.markdown("---")

if not st.session_state.conversation:
    st.markdown("""
    <div style="text-align:center; padding:3rem 1rem;">
        <div style="font-size:2.5rem; margin-bottom:1rem;">💬</div>
        <div style="font-size:1rem; color:#5a5a6a;">Hacé tu primera pregunta sobre los documentos</div>
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

if not vs_id:
    st.info("⏳ Inicializando Vector Store, esperá unos segundos y recargá.")
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
