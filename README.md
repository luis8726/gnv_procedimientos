# 📚 PDF Knowledge Base — Streamlit + OpenAI Vector Store + AWS S3

Sistema de consulta de documentos PDF con sincronización **automática y transparente**.
Cuando subís, modificás o eliminás un PDF en S3, el Vector Store se actualiza solo.

---

## Arquitectura

```
S3 Bucket (PUT/DELETE)
     │  evento automático
     ▼
SQS Queue  ←── S3 notifica en tiempo real
     │
     ▼
worker.py  ←── proceso independiente, siempre activo
     │          hace long-polling a SQS (20s)
     ▼
sync_engine.py → OpenAI Vector Store
     │
     ▼
sync_state.json  ←── Streamlit lee esto (solo lectura)
     │
     ▼
app.py (Streamlit)  ←── el usuario consulta
```

**Dos procesos independientes:**
- `worker.py` — sincronización (corre siempre en background)
- `app.py` — interfaz Streamlit (MVP) / WhatsApp en producción

---

## Setup: paso a paso

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus credenciales
```

### 3. Configurar AWS (una sola vez)

#### 3a. Crear la cola SQS

1. Ir a **AWS Console → SQS → Create queue**
2. Tipo: **Standard** (no FIFO)
3. Nombre: `pdf-sync-queue` (o el que prefieras)
4. En **Access policy**, agregar permiso para que S3 pueda escribir:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "s3.amazonaws.com" },
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:pdf-sync-queue",
      "Condition": {
        "ArnLike": {
          "aws:SourceArn": "arn:aws:s3:::TU-BUCKET"
        }
      }
    }
  ]
}
```

5. Copiar la **Queue URL** → pegarla en `.env` como `SQS_QUEUE_URL`

#### 3b. Configurar notificaciones en el bucket S3

1. Ir a **S3 → tu bucket → Properties → Event notifications → Create**
2. Nombre: `pdf-changes`
3. Prefix: el mismo que tenés en `S3_PREFIX` (ej: `documentos/`)
4. Suffix: `.pdf`
5. Event types: marcar **All object create events** + **Object removal**
6. Destination: **SQS queue** → seleccionar `pdf-sync-queue`

#### 3c. Permisos IAM mínimos

El usuario/rol necesita:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:ListBucket",
    "s3:GetObject",
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:GetQueueAttributes"
  ],
  "Resource": [
    "arn:aws:s3:::TU-BUCKET",
    "arn:aws:s3:::TU-BUCKET/*",
    "arn:aws:sqs:REGION:ACCOUNT:pdf-sync-queue"
  ]
}
```

### 4. Correr

**Terminal 1 — Worker de sincronización:**
```bash
python worker.py
```

**Terminal 2 — App Streamlit:**
```bash
streamlit run app.py
```

El worker hace una sincronización inicial al arrancar y luego queda escuchando.
Desde ese momento, cualquier cambio en S3 se refleja en el VS automáticamente.

---

## Estructura del proyecto

```
pdf-vs-app/
├── app.py                    # Streamlit — UI (solo lectura de estado)
├── worker.py                 # Worker — sincronización autónoma
├── requirements.txt
├── .env.example
├── sync_state.json           # Auto-generado: canal worker ↔ Streamlit
│
├── sync/
│   ├── sync_engine.py        # Procesa eventos S3 individuales
│   ├── sqs_listener.py       # Long-polling a SQS
│   ├── s3_connector.py       # Listado y descarga desde S3
│   └── state.py              # Persistencia del estado compartido
│
├── vectorstore/
│   └── vs_manager.py         # CRUD del OpenAI Vector Store
│
└── chat/
    └── chat_engine.py        # Chat con GPT-4o + file_search
```

---

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | API Key de OpenAI |
| `AWS_ACCESS_KEY_ID` | ✅ | Access Key de AWS |
| `AWS_SECRET_ACCESS_KEY` | ✅ | Secret Key de AWS |
| `AWS_REGION` | ✅ | Región (ej: `us-east-1`) |
| `S3_BUCKET_NAME` | ✅ | Nombre del bucket S3 |
| `SQS_QUEUE_URL` | ✅ | URL completa de la cola SQS |
| `S3_PREFIX` | — | Carpeta dentro del bucket (ej: `docs/`) |
| `OPENAI_VECTOR_STORE_ID` | — | Forzar VS existente (opcional) |
| `APP_TITLE` | — | Título de la app (default: `Base de Conocimiento`) |

---

## Migración a WhatsApp (producción)

El `worker.py` y toda la capa de `sync/` no cambia nada.
Solo se reemplaza `app.py` (Streamlit) por el webhook FastAPI de WhatsApp:

```
worker.py  →  sin cambios
sync/      →  sin cambios
vectorstore/ → sin cambios
chat/chat_engine.py → mismo código, lo llama el webhook

app.py (Streamlit MVP)
    ↓ reemplazar por
main.py (FastAPI webhook)  →  WhatsApp Business API
```

---

## Costos estimados (referencia)

| Componente | Estimado/mes |
|---|---|
| OpenAI Vector Store | ~$0.10/GB/día indexado |
| OpenAI GPT-4o (queries) | ~$10–30 según volumen |
| AWS S3 + SQS | < $1 para < 20 PDFs |
| Streamlit Cloud | Gratis (plan hobby) |
