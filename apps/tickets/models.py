"""Modelos del módulo Tickets.

Implementa la máquina de estados completa definida en el master prompt:

    CREADO_PENDIENTE_IA → ANALIZADO_POR_IA → PENDIENTE_VALIDACION
    → ASIGNADO → EN_CAMINO → EN_PROGRESO → RESUELTO

Adicionalmente se modelan evidencias multimedia y un historial de
transiciones de estado para auditoría operativa.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class TicketStatus(models.TextChoices):
    CREADO_PENDIENTE_IA = 'CREADO_PENDIENTE_IA', _('Creado · Pendiente IA')
    ANALIZADO_POR_IA = 'ANALIZADO_POR_IA', _('Analizado por IA')
    PENDIENTE_VALIDACION = 'PENDIENTE_VALIDACION', _('Pendiente Validación')
    ASIGNADO = 'ASIGNADO', _('Asignado')
    EN_CAMINO = 'EN_CAMINO', _('En Camino')
    EN_PROGRESO = 'EN_PROGRESO', _('En Progreso')
    RESUELTO = 'RESUELTO', _('Resuelto')
    CANCELADO = 'CANCELADO', _('Cancelado')


class TicketPriority(models.TextChoices):
    BAJA = 'BAJA', _('Baja')
    MEDIA = 'MEDIA', _('Media')
    ALTA = 'ALTA', _('Alta')
    CRITICA = 'CRITICA', _('Crítica')


class TicketCategory(models.TextChoices):
    PLOMERIA = 'PLOMERIA', _('Plomería')
    ELECTRICIDAD = 'ELECTRICIDAD', _('Electricidad')
    INFRAESTRUCTURA = 'INFRAESTRUCTURA', _('Infraestructura')
    LIMPIEZA = 'LIMPIEZA', _('Limpieza')
    SEGURIDAD = 'SEGURIDAD', _('Seguridad')
    OTRO = 'OTRO', _('Otro')


class Ticket(models.Model):
    """Orden de mantenimiento dentro del sistema.

    Una sola unidad de negocio que atraviesa toda la máquina de estados.
    Las transiciones se realizan exclusivamente desde
    :func:`apps.tickets.services.transitions.transition_ticket`.
    """

    # ── Relaciones ──────────────────────────────────────────────────────
    unidad = models.ForeignKey(
        'properties.Unidad',
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name=_('Unidad'),
    )
    inquilino = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='tickets_creados',
        limit_choices_to={'role': 'INQUILINO'},
        verbose_name=_('Inquilino'),
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets_asignados',
        limit_choices_to={'role': 'TECNICO'},
        verbose_name=_('Técnico Asignado'),
    )

    # ── Datos del incidente ─────────────────────────────────────────────
    titulo = models.CharField(_('Título'), max_length=200)
    descripcion = models.TextField(_('Descripción detallada'))
    categoria = models.CharField(
        _('Categoría'),
        max_length=20,
        choices=TicketCategory.choices,
        default=TicketCategory.OTRO,
        blank=True,
    )

    # ── Máquina de estados ──────────────────────────────────────────────
    estado = models.CharField(
        _('Estado'),
        max_length=30,
        choices=TicketStatus.choices,
        default=TicketStatus.CREADO_PENDIENTE_IA,
    )
    prioridad = models.CharField(
        _('Prioridad'),
        max_length=10,
        choices=TicketPriority.choices,
        default=TicketPriority.MEDIA,
    )

    # ── Sugerencia IA (rellenado por ai_agent) ─────────────────────────
    ia_descripcion_tecnica = models.TextField(_('Descripción técnica IA'), blank=True)
    ia_categoria_sugerida = models.CharField(_('Categoría sugerida IA'), max_length=20, blank=True)
    ia_prioridad_sugerida = models.CharField(_('Prioridad sugerida IA'), max_length=10, blank=True)
    ia_tecnico_sugerido = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets_sugeridos_ia',
        limit_choices_to={'role': 'TECNICO'},
        verbose_name=_('Técnico sugerido IA'),
    )
    ia_razon_asignacion = models.TextField(_('Razón asignación IA'), blank=True)
    ia_confianza = models.DecimalField(
        _('Confianza IA'),
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('Valor 0.00 – 1.00 reportado por el modelo.'),
    )

    # ── Resolución ──────────────────────────────────────────────────────
    notas_resolucion = models.TextField(_('Notas de resolución'), blank=True)
    resuelto_en = models.DateTimeField(_('Fecha de resolución'), null=True, blank=True)

    # ── Auditoría ───────────────────────────────────────────────────────
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Ticket')
        verbose_name_plural = _('Tickets')
        ordering = ['-creado_en']
        indexes = [
            models.Index(fields=['estado']),
            models.Index(fields=['prioridad']),
            models.Index(fields=['inquilino']),
            models.Index(fields=['tecnico']),
        ]

    def __str__(self) -> str:
        return f'#{self.id:04d} · {self.titulo}'

    # ── Helpers de presentación ─────────────────────────────────────────
    @property
    def codigo(self) -> str:
        """Identificador legible del ticket: TKT-0001."""
        return f'TKT-{self.id:04d}' if self.id else 'TKT-NUEVO'

    @property
    def is_terminal(self) -> bool:
        return self.estado in {TicketStatus.RESUELTO, TicketStatus.CANCELADO}

    @property
    def is_pendiente_validacion(self) -> bool:
        return self.estado == TicketStatus.PENDIENTE_VALIDACION


def evidencia_upload_path(instance: 'EvidenciaTicket', filename: str) -> str:
    """Ruta predecible: tickets/<id>/<momento>/<filename>."""
    return f'tickets/{instance.ticket_id}/evidencias/{filename}'


class EvidenciaTicket(models.Model):
    """Archivo (foto o documento) adjunto a un ticket.

    Un ticket puede tener N evidencias en el momento de creación
    (reportadas por el inquilino) y/o al cierre (subidas por el técnico).
    """

    class Momento(models.TextChoices):
        REPORTE = 'REPORTE', _('Reporte inicial')
        RESOLUCION = 'RESOLUCION', _('Resolución')

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='evidencias',
    )
    archivo = models.ImageField(_('Archivo'), upload_to=evidencia_upload_path)
    momento = models.CharField(
        _('Momento'),
        max_length=15,
        choices=Momento.choices,
        default=Momento.REPORTE,
    )
    descripcion = models.CharField(_('Descripción'), max_length=255, blank=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='evidencias_subidas',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Evidencia')
        verbose_name_plural = _('Evidencias')
        ordering = ['creado_en']

    def __str__(self) -> str:
        return f'Evidencia {self.ticket.codigo} ({self.get_momento_display()})'


class MensajeTicket(models.Model):
    """Hilo de comunicación directo entre técnico e inquilino en un ticket."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='mensajes',
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='mensajes_ticket',
    )
    mensaje = models.TextField(_('Mensaje'), max_length=1000)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Mensaje')
        verbose_name_plural = _('Mensajes')
        ordering = ['creado_en']

    def __str__(self) -> str:
        return f'{self.ticket.codigo} · {self.autor.get_full_name()}'


class HistorialEstado(models.Model):
    """Registro auditable de cada transición de estado del ticket."""

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='historial',
    )
    estado_anterior = models.CharField(
        _('Estado anterior'),
        max_length=30,
        choices=TicketStatus.choices,
        blank=True,
    )
    estado_nuevo = models.CharField(
        _('Estado nuevo'),
        max_length=30,
        choices=TicketStatus.choices,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transiciones_realizadas',
        verbose_name=_('Realizada por'),
    )
    nota = models.TextField(_('Nota'), blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Transición de estado')
        verbose_name_plural = _('Historial de estados')
        ordering = ['creado_en']

    def __str__(self) -> str:
        return f'{self.ticket.codigo}: {self.estado_anterior or "—"} → {self.estado_nuevo}'
