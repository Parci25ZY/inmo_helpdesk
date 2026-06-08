"""Modelos del agente IA: base de conocimiento RAG y conversaciones."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class KnowledgeCategory(models.TextChoices):
    PLOMERIA = 'PLOMERIA', _('Plomería')
    ELECTRICIDAD = 'ELECTRICIDAD', _('Electricidad')
    SEGURIDAD = 'SEGURIDAD', _('Seguridad')
    REGLAMENTO = 'REGLAMENTO', _('Reglamento')
    GENERAL = 'GENERAL', _('General')


class KnowledgeDocument(models.Model):
    """Documento fuente indexado para RAG (FAQs, reglamento, manuales)."""

    titulo = models.CharField(_('Título'), max_length=200)
    categoria = models.CharField(
        _('Categoría'),
        max_length=20,
        choices=KnowledgeCategory.choices,
        default=KnowledgeCategory.GENERAL,
    )
    contenido = models.TextField(_('Contenido'))
    activo = models.BooleanField(_('Activo'), default=True)
    indexado = models.BooleanField(
        _('Indexado'),
        default=False,
        help_text=_('True cuando los chunks y embeddings ya fueron generados.'),
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Documento de conocimiento')
        verbose_name_plural = _('Documentos de conocimiento')
        ordering = ['categoria', 'titulo']

    def __str__(self) -> str:
        return self.titulo


class KnowledgeChunk(models.Model):
    """Fragmento de un documento con su embedding vectorial (JSON)."""

    documento = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name='chunks',
    )
    indice = models.PositiveIntegerField(_('Índice'))
    contenido = models.TextField(_('Contenido del fragmento'))
    embedding = models.JSONField(
        _('Embedding'),
        default=list,
        help_text=_('Vector numérico generado por Gemini gemini-embedding-001.'),
    )
    token_count = models.PositiveIntegerField(_('Tokens estimados'), default=0)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Fragmento de conocimiento')
        verbose_name_plural = _('Fragmentos de conocimiento')
        ordering = ['documento', 'indice']
        unique_together = [('documento', 'indice')]
        indexes = [
            models.Index(fields=['documento']),
        ]

    def __str__(self) -> str:
        return f'{self.documento.titulo} · chunk {self.indice}'


class ChatSession(models.Model):
    """Sesión conversacional del chatbot por usuario."""

    class Estado(models.TextChoices):
        ACTIVA = 'ACTIVA', _('Activa')
        CERRADA = 'CERRADA', _('Cerrada')

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='chat_sessions',
    )
    ticket = models.ForeignKey(
        'tickets.Ticket',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_sessions',
        verbose_name=_('Ticket vinculado'),
    )
    titulo = models.CharField(_('Título'), max_length=200, blank=True)
    estado = models.CharField(
        _('Estado'),
        max_length=10,
        choices=Estado.choices,
        default=Estado.ACTIVA,
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Sesión de chat')
        verbose_name_plural = _('Sesiones de chat')
        ordering = ['-actualizado_en']
        indexes = [
            models.Index(fields=['usuario', 'estado']),
        ]

    def __str__(self) -> str:
        return self.titulo or f'Chat {self.uuid.hex[:8]}'


class ChatMessage(models.Model):
    """Mensaje individual dentro de una sesión de chat."""

    class Rol(models.TextChoices):
        USUARIO = 'USUARIO', _('Usuario')
        ASISTENTE = 'ASISTENTE', _('Asistente')
        SISTEMA = 'SISTEMA', _('Sistema')

    class EstadoProceso(models.TextChoices):
        COMPLETADO = 'COMPLETADO', _('Completado')
        PENDIENTE = 'PENDIENTE', _('Pendiente')
        ERROR = 'ERROR', _('Error')

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sesion = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='mensajes',
    )
    rol = models.CharField(_('Rol'), max_length=12, choices=Rol.choices)
    contenido = models.TextField(_('Contenido'))
    estado_proceso = models.CharField(
        _('Estado de procesamiento'),
        max_length=12,
        choices=EstadoProceso.choices,
        default=EstadoProceso.COMPLETADO,
    )
    metadata = models.JSONField(_('Metadatos'), default=dict, blank=True)
    chunks_usados = models.ManyToManyField(
        KnowledgeChunk,
        blank=True,
        related_name='mensajes',
        verbose_name=_('Fragmentos RAG utilizados'),
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Mensaje de chat')
        verbose_name_plural = _('Mensajes de chat')
        ordering = ['creado_en']
        indexes = [
            models.Index(fields=['sesion', 'creado_en']),
            models.Index(fields=['estado_proceso']),
        ]

    def __str__(self) -> str:
        preview = self.contenido[:60] + ('…' if len(self.contenido) > 60 else '')
        return f'{self.get_rol_display()}: {preview}'
