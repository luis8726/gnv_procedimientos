"""
chat_engine.py — Compatible con openai >= 2.0
Usa la Responses API con file_search tool nativa.
"""

import os
from openai import OpenAI
from vectorstore.vs_manager import get_or_create_vector_store


def get_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_system_prompt() -> str:
    app_title = os.getenv("APP_TITLE", "Base de Conocimiento")
    return f"""Sos un asistente experto que responde preguntas basándose exclusivamente en los documentos técnicos y manuales disponibles en la base de conocimiento.

Reglas:
- Respondé siempre en español, de manera clara y estructurada.
- Si la respuesta está en los documentos, citá el nombre del documento fuente.
- Si la información NO está en los documentos, decilo explícitamente: "Esta información no se encuentra en los documentos disponibles."
- No inventes información ni uses conocimiento externo a los documentos.
- Usá listas y formatos cuando sea útil para la legibilidad.

Sistema: {app_title}"""


def chat(user_message: str, conversation_history: list[dict]) -> tuple[str, list[dict]]:
    client = get_client()
    vs_id = get_or_create_vector_store()

    # Construir input: historial + mensaje nuevo
    input_messages = []
    for msg in conversation_history:
        input_messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    input_messages.append({"role": "user", "content": user_message})

    response = client.responses.create(
        model="gpt-4o",
        instructions=build_system_prompt(),
        input=input_messages,
        tools=[{
            "type": "file_search",
            "vector_store_ids": [vs_id],
            "max_num_results": 10,
        }],
        temperature=0.2,
    )

    # Extraer texto de la respuesta
    response_text = ""
    for output in response.output:
        if output.type == "message":
            for content in output.content:
                if content.type == "output_text":
                    response_text += content.text

    if not response_text:
        response_text = "No pude encontrar información relevante en los documentos."

    # Actualizar historial
    updated_history = list(conversation_history)
    updated_history.append({"role": "user", "content": user_message})
    updated_history.append({"role": "assistant", "content": response_text})

    # Limitar a últimas 20 interacciones
    if len(updated_history) > 40:
        updated_history = updated_history[-40:]

    return response_text, updated_history
