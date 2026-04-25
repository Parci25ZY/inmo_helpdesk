from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class Ticket(models.Model):
    """
    Modelo principal para la gestión de incidencias en la inmobiliaria.
    """
    class Status(models.TextChoices):
        PENDIENTE = 'PENDIENTE', _('Pendiente')
        EN_PROGRESO = 'EN_PROGRESO', _('En Progreso')
        RESUELTO = 'RESUELTO', _('Resuelto')
        CANCELADO = 'CANCELADO', _('Cancelado')

    class Priority(models.TextChoices):
        BAJA = 'BAJA', _('Baja')
        MEDIA = 'MEDIA', _('Media')
        ALTA = 'ALTA', _('Alta')
        URGENTE = 'URGENTE', _('Urgente')

    # --- Relaciones ---
    inquilino = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets_creados',
        limit_choices_to={'rol': 'INQUILINO'},
        verbose_name=_("Inquilino")
    )
    tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets_asignados',
        limit_choices_to={'rol': 'TECNICO'},
        verbose_name=_("Técnico Asignado")
    )

    # --- Información del Ticket ---
    titulo = models.CharField(_("Título de la incidencia"), max_length=200)
    descripcion = models.TextField(_("Descripción detallada"))
    categoria = models.CharField(_("Categoría"), max_length=100, blank=True) # Aquí actuará la IA
    
    estado = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDIENTE,
        verbose_name=_("Estado")
    )
    prioridad = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIA,
        verbose_name=_("Prioridad")
    )

    # --- Auditoría ---
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Ticket")
        verbose_name_plural = _("Tickets")
        ordering = ['-creado_en']

    def __str__(self):
        return f"#{self.id} - {self.titulo} ({self.get_estado_display()})"