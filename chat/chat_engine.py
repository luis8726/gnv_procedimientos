"""
chat_engine.py — Compatible con openai >= 2.0
"""

import os
from openai import OpenAI
from vectorstore.vs_manager import get_or_create_vector_store


def get_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def build_system_prompt() -> str:
    app_title = os.getenv("APP_TITLE", "Base de Conocimiento")
    return f"""Sos un asistente experto de {app_title}. Tenés acceso a documentos técnicos cargados en tu base de conocimiento y SIEMPRE debés buscar en ellos antes de responder.

Reglas:
- SIEMPRE buscá en los documentos disponibles antes de responder.
- Respondé en español, de manera clara y estructurada.
- Citá el nombre del documento fuente cuando uses información de él.
- Si después de buscar genuinamente no encontrás la información, decilo: "No encontré información sobre esto en los documentos disponibles."
- Usá listas y formatos cuando sea útil."""


def chat(user_message: str, conversation_history: list[dict]) -> tuple[str, list[dict]]:
    client = get_client()
    vs_id = get_or_create_vector_store()

    input_messages = []
    for msg in conversation_history:
        input_messages.append({"role": msg["role"], "content": msg["content"]})
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

    response_text = ""
    for output in response.output:
        if output.type == "message":
            for content in output.content:
                if content.type == "output_text":
                    response_text += content.text

    if not response_text:
        response_text = "No pude encontrar información relevante en los documentos."

    updated_history = list(conversation_history)
    updated_history.append({"role": "user", "content": user_message})
    updated_history.append({"role": "assistant", "content": response_text})

    if len(updated_history) > 40:
        updated_history = updated_history[-40:]

    return response_text, updated_history
