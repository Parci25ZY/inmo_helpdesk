from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.ai_agent.models import (
    ChatMessage,
    ChatSession,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDocument,
)
from apps.ai_agent.services.chat import process_user_message
from apps.ai_agent.services.rag import index_document, retrieve_relevant_chunks


def _make_user(role=CustomUser.Roles.INQUILINO, email='user@test.com'):
    return CustomUser.objects.create_user(
        email=email, password='clave12345', first_name='Test', last_name='User', role=role,
    )


def _make_doc(activo=True, indexado=True, titulo='Doc'):
    return KnowledgeDocument.objects.create(
        titulo=titulo, categoria=KnowledgeCategory.GENERAL, contenido='contenido',
        activo=activo, indexado=indexado,
    )


def _make_chunk(documento, indice, embedding, contenido='contenido de prueba'):
    return KnowledgeChunk.objects.create(
        documento=documento, indice=indice, contenido=contenido, embedding=embedding,
    )


@pytest.mark.django_db
class TestRetrieveRelevantChunks:
    def test_returns_chunks_above_threshold_ordered_by_score(self):
        doc = _make_doc()
        cercano = _make_chunk(doc, 0, [1.0, 0.0, 0.0], 'muy relevante')
        lejano = _make_chunk(doc, 1, [0.0, 1.0, 0.0], 'poco relevante')

        resultados = retrieve_relevant_chunks([1.0, 0.0, 0.0], top_k=5, min_score=0.5)

        assert resultados == [cercano]
        assert lejano not in resultados

    def test_respects_top_k(self):
        doc = _make_doc()
        for i in range(5):
            _make_chunk(doc, i, [1.0, 0.0, 0.0])

        resultados = retrieve_relevant_chunks([1.0, 0.0, 0.0], top_k=2, min_score=0.0)

        assert len(resultados) == 2

    def test_ignores_inactive_or_unindexed_documents(self):
        inactivo = _make_doc(activo=False, indexado=True, titulo='Inactivo')
        sin_indexar = _make_doc(activo=True, indexado=False, titulo='SinIndexar')
        _make_chunk(inactivo, 0, [1.0, 0.0, 0.0])
        _make_chunk(sin_indexar, 0, [1.0, 0.0, 0.0])

        resultados = retrieve_relevant_chunks([1.0, 0.0, 0.0], min_score=0.0)

        assert resultados == []

    def test_empty_when_no_chunks(self):
        assert retrieve_relevant_chunks([1.0, 0.0, 0.0]) == []

    def test_skips_chunks_without_embedding(self):
        doc = _make_doc()
        _make_chunk(doc, 0, [])

        resultados = retrieve_relevant_chunks([1.0, 0.0, 0.0], min_score=0.0)

        assert resultados == []


@pytest.mark.django_db
class TestIndexDocument:
    def test_creates_chunks_with_embeddings(self):
        doc = KnowledgeDocument.objects.create(
            titulo='Doc', categoria=KnowledgeCategory.GENERAL,
            contenido='Texto de prueba largo. ' * 50, activo=True,
        )

        with patch('apps.ai_agent.services.rag.embed_text', return_value=[0.1, 0.2, 0.3]):
            cantidad = index_document(doc)

        doc.refresh_from_db()
        assert cantidad > 0
        assert doc.indexado is True
        assert doc.chunks.count() == cantidad
        assert all(chunk.embedding == [0.1, 0.2, 0.3] for chunk in doc.chunks.all())

    def test_reindexing_replaces_previous_chunks(self):
        doc = KnowledgeDocument.objects.create(
            titulo='Doc', categoria=KnowledgeCategory.GENERAL, contenido='Contenido corto', activo=True,
        )
        with patch('apps.ai_agent.services.rag.embed_text', return_value=[1.0]):
            index_document(doc)
            primera_cantidad = doc.chunks.count()
            index_document(doc)
            segunda_cantidad = doc.chunks.count()

        assert primera_cantidad == segunda_cantidad == 1

    def test_failed_embedding_stores_empty_vector_without_crashing(self):
        doc = KnowledgeDocument.objects.create(
            titulo='Doc', categoria=KnowledgeCategory.GENERAL, contenido='Contenido corto', activo=True,
        )
        with patch('apps.ai_agent.services.rag.embed_text', side_effect=RuntimeError('API caída')):
            cantidad = index_document(doc)

        assert cantidad > 0
        assert all(chunk.embedding == [] for chunk in doc.chunks.all())


@pytest.mark.django_db
class TestProcessUserMessage:
    def _crear_sesion_con_mensajes(self, texto_usuario='¿Cómo cierro la llave de paso?'):
        usuario = _make_user()
        sesion = ChatSession.objects.create(usuario=usuario)
        user_msg = ChatMessage.objects.create(
            sesion=sesion, rol=ChatMessage.Rol.USUARIO, contenido=texto_usuario,
            estado_proceso=ChatMessage.EstadoProceso.COMPLETADO,
        )
        asistente_msg = ChatMessage.objects.create(
            sesion=sesion, rol=ChatMessage.Rol.ASISTENTE, contenido='',
            estado_proceso=ChatMessage.EstadoProceso.PENDIENTE,
        )
        return sesion, user_msg, asistente_msg

    def test_success_path_uses_llm_result_and_persists_chunks_used(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()
        doc = _make_doc()
        chunk = _make_chunk(doc, 0, [1.0, 0.0, 0.0])

        resultado_llm = {
            'respuesta': 'Cierra la llave girándola en sentido horario.',
            'requiere_tecnico': False,
            'confianza': 0.9,
        }

        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            return_value=(resultado_llm, [chunk]),
        ):
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.COMPLETADO
        assert actualizado.contenido == resultado_llm['respuesta']
        assert actualizado.metadata['requiere_tecnico'] is False
        assert actualizado.metadata['chunks_count'] == 1
        assert list(actualizado.chunks_usados.all()) == [chunk]

        sesion.refresh_from_db()
        assert sesion.titulo == user_msg.contenido[:120]

    def test_langchain_success_does_not_duplicate_embedding_or_retrieval(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()
        resultado_llm = {'respuesta': 'Listo.', 'requiere_tecnico': False, 'confianza': 0.9}

        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            return_value=(resultado_llm, []),
        ), \
             patch('apps.ai_agent.services.chat.embed_query') as mock_embed, \
             patch('apps.ai_agent.services.chat.retrieve_relevant_chunks') as mock_retrieve:
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.COMPLETADO
        mock_embed.assert_not_called()
        mock_retrieve.assert_not_called()

    def test_falls_back_to_native_gemini_when_langchain_fails(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()
        resultado_llm = {'respuesta': 'Respuesta nativa', 'requiere_tecnico': False, 'confianza': 0.7}

        with patch('apps.ai_agent.services.chat.embed_query', return_value=[1.0, 0.0, 0.0]), \
             patch('apps.ai_agent.services.chat.retrieve_relevant_chunks', return_value=[]), \
             patch(
                 'apps.ai_agent.services.langchain_rag.generate_with_langchain',
                 side_effect=RuntimeError('langchain caído'),
             ), \
             patch('apps.ai_agent.services.chat.generate_chat_response', return_value=resultado_llm):
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.COMPLETADO
        assert actualizado.contenido == 'Respuesta nativa'

    def test_missing_user_message_returns_friendly_error(self):
        usuario = _make_user()
        sesion = ChatSession.objects.create(usuario=usuario)
        asistente_msg = ChatMessage.objects.create(
            sesion=sesion, rol=ChatMessage.Rol.ASISTENTE, contenido='',
            estado_proceso=ChatMessage.EstadoProceso.PENDIENTE,
        )

        actualizado = process_user_message(asistente_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.ERROR
        assert 'No encontré tu mensaje' in actualizado.contenido

    def test_explicit_user_message_wins_even_when_timestamps_tie(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()
        empate = timezone.now()
        ChatMessage.objects.filter(pk__in=[user_msg.pk, asistente_msg.pk]).update(creado_en=empate)
        user_msg.refresh_from_db()
        asistente_msg.refresh_from_db()
        assert user_msg.creado_en == asistente_msg.creado_en

        resultado_llm = {'respuesta': 'Listo.', 'requiere_tecnico': False, 'confianza': 0.8}
        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            return_value=(resultado_llm, []),
        ):
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.COMPLETADO
        assert actualizado.contenido == 'Listo.'

    def test_fallback_lookup_still_works_without_explicit_user_message(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()
        ChatMessage.objects.filter(pk=user_msg.pk).update(
            creado_en=timezone.now() - timedelta(seconds=1),
        )

        resultado_llm = {'respuesta': 'Vía fallback.', 'requiere_tecnico': False, 'confianza': 0.5}
        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            return_value=(resultado_llm, []),
        ):
            actualizado = process_user_message(asistente_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.COMPLETADO
        assert actualizado.contenido == 'Vía fallback.'

    def test_gemini_failure_sets_error_state_and_keeps_metadata(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes()

        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            side_effect=RuntimeError('GEMINI_API_KEY no configurada'),
        ), patch(
            'apps.ai_agent.services.chat.embed_query',
            side_effect=RuntimeError('GEMINI_API_KEY no configurada'),
        ):
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.estado_proceso == ChatMessage.EstadoProceso.ERROR
        assert 'error' in actualizado.metadata
        assert 'Hubo un error' in actualizado.contenido

    def test_emergency_keyword_forces_requiere_tecnico_true(self):
        sesion, user_msg, asistente_msg = self._crear_sesion_con_mensajes(
            texto_usuario='Huele a gas en mi departamento, ayuda',
        )
        resultado_llm = {'respuesta': 'Evacúa y llama al 911.', 'requiere_tecnico': False, 'confianza': 0.6}

        with patch(
            'apps.ai_agent.services.langchain_rag.generate_with_langchain',
            return_value=(resultado_llm, []),
        ):
            actualizado = process_user_message(asistente_msg, user_msg)

        assert actualizado.metadata['requiere_tecnico'] is True


@pytest.mark.django_db
class TestProcessChatMessageTask:
    def test_passes_user_message_through_to_process_user_message(self):
        from apps.ai_agent.tasks import process_chat_message

        usuario = _make_user()
        sesion = ChatSession.objects.create(usuario=usuario)
        user_msg = ChatMessage.objects.create(
            sesion=sesion, rol=ChatMessage.Rol.USUARIO, contenido='hola',
            estado_proceso=ChatMessage.EstadoProceso.COMPLETADO,
        )
        asistente_msg = ChatMessage.objects.create(
            sesion=sesion, rol=ChatMessage.Rol.ASISTENTE, contenido='',
            estado_proceso=ChatMessage.EstadoProceso.PENDIENTE,
        )

        with patch('apps.ai_agent.tasks.process_user_message') as mock_process:
            mock_process.return_value = asistente_msg
            process_chat_message.run(asistente_msg.pk, user_msg.pk)

        mock_process.assert_called_once()
        args, _ = mock_process.call_args
        assert args[0].pk == asistente_msg.pk
        assert args[1].pk == user_msg.pk

    def test_missing_assistant_message_returns_error_dict(self):
        from apps.ai_agent.tasks import process_chat_message

        resultado = process_chat_message.run(999999, None)

        assert resultado == {'error': 'mensaje no encontrado'}


@pytest.mark.django_db
class TestSeedKnowledgeBaseCommand:
    def test_creates_all_seed_documents(self):
        with patch(
            'apps.ai_agent.management.commands.seed_knowledge_base.index_knowledge_document',
        ) as mock_task:
            call_command('seed_knowledge_base')

        from apps.ai_agent.management.commands.seed_knowledge_base import SEED_DOCUMENTS

        assert KnowledgeDocument.objects.count() == len(SEED_DOCUMENTS)
        assert mock_task.delay.call_count == len(SEED_DOCUMENTS)

    def test_is_idempotent_without_force(self):
        with patch('apps.ai_agent.management.commands.seed_knowledge_base.index_knowledge_document'):
            call_command('seed_knowledge_base')
            call_command('seed_knowledge_base')

        from apps.ai_agent.management.commands.seed_knowledge_base import SEED_DOCUMENTS

        assert KnowledgeDocument.objects.count() == len(SEED_DOCUMENTS)

    def test_force_reindexes_existing_documents(self):
        with patch(
            'apps.ai_agent.management.commands.seed_knowledge_base.index_knowledge_document',
        ) as mock_task:
            call_command('seed_knowledge_base')
            mock_task.reset_mock()
            call_command('seed_knowledge_base', '--force')

        from apps.ai_agent.management.commands.seed_knowledge_base import SEED_DOCUMENTS

        assert mock_task.delay.call_count == len(SEED_DOCUMENTS)
