"""Integración LangChain: retriever personalizado + cadena conversacional."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from langchain_core.documents import Document
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic import BaseModel, Field

from apps.ai_agent.models import KnowledgeChunk

from .rag import retrieve_relevant_chunks


class EscalationSchema(BaseModel):
    respuesta: str = Field(
        description='Guía completa en español con pasos numerados cuando aplique. '
        'Resuelve la consulta sin mencionar ticket si no hace falta.',
    )
    requiere_tecnico: bool = Field(
        description='False por defecto. True SOLO si hay daño grave, emergencia, riesgo '
        'o el inquilino no puede resolver con los pasos del contexto.',
    )
    titulo_ticket_sugerido: str = Field(default='', description='Título breve si escala.')
    descripcion_ticket_sugerida: str = Field(default='', description='Descripción del incidente.')
    categoria_sugerida: str = Field(default='OTRO')
    prioridad_sugerida: str = Field(default='MEDIA')
    confianza: float = Field(default=0.5)


class PostgresRAGRetriever(BaseRetriever):
    """Retriever LangChain que consulta KnowledgeChunk en PostgreSQL."""

    top_k: int = 4

    def _get_relevant_documents(self, query: str) -> list[Document]:
        embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.GEMINI_EMBEDDING_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
        )
        query_vector = embeddings.embed_query(query)
        chunks = retrieve_relevant_chunks(query_vector, top_k=self.top_k)
        return [
            Document(
                page_content=chunk.contenido,
                metadata={
                    'titulo': chunk.documento.titulo,
                    'categoria': chunk.documento.get_categoria_display(),
                },
            )
            for chunk in chunks
        ]


def generate_with_langchain(
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Genera respuesta estructurada usando LangChain + retriever RAG."""
    retriever = PostgresRAGRetriever()
    docs = retriever.invoke(user_message)
    context = '\n\n'.join(
        f"[{i + 1}] {d.metadata.get('titulo', 'FAQ')} ({d.metadata.get('categoria', '')}):\n{d.page_content}"
        for i, d in enumerate(docs)
    ) or '(Sin contexto RAG disponible.)'

    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_CHAT_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.3,
    )

    parser = JsonOutputParser(pydantic_object=EscalationSchema)

    prompt = ChatPromptTemplate.from_messages([
        ('system', """Eres el asistente virtual de InmoHelpdesk para mantenimiento inmobiliario.
Prioriza resolver la consulta SIN técnico: guías paso a paso con el contexto RAG.
requiere_tecnico=false salvo emergencias, daño grave o falla tras intentar los pasos.
Responde en español. {format_instructions}"""),
        ('human', """CONTEXTO RAG:
{context}

PREGUNTA:
{question}"""),
    ])

    chain = prompt | llm | parser
    result = chain.invoke({
        'context': context,
        'question': user_message,
        'format_instructions': parser.get_format_instructions(),
    })

    if isinstance(result, dict):
        return result
    return result.model_dump()
