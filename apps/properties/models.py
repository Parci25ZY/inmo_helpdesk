from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Edificio(models.Model):
    """Inmueble principal (edificio, condominio o conjunto residencial).

    Agrupa una o varias :class:`Unidad`, sirve como contexto geográfico
    para los tickets y como unidad de reporte para el administrador.
    """

    nombre = models.CharField(
        _('Nombre del edificio'),
        max_length=120,
    )
    codigo = models.CharField(
        _('Código interno'),
        max_length=20,
        unique=True,
        help_text=_('Identificador corto único, ej. "EDI-A01".'),
    )
    direccion = models.CharField(_('Dirección'), max_length=255)
    ciudad = models.CharField(_('Ciudad'), max_length=80, default='Guayaquil')
    descripcion = models.TextField(_('Descripción'), blank=True)
    activo = models.BooleanField(_('Activo'), default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Edificio')
        verbose_name_plural = _('Edificios')
        ordering = ['nombre']

    def __str__(self) -> str:
        return f'{self.codigo} · {self.nombre}'

    @property
    def total_unidades(self) -> int:
        return self.unidades.count()

    @property
    def unidades_ocupadas(self) -> int:
        return self.unidades.filter(inquilino__isnull=False).count()


class Unidad(models.Model):
    """Espacio individual habitable o comercial dentro de un Edificio.

    Cada unidad puede tener un único inquilino asignado (relación 1‑1 lógica).
    Los tickets se vinculan a una unidad para dar contexto al mantenimiento.
    """

    class Tipo(models.TextChoices):
        DEPARTAMENTO = 'DEPARTAMENTO', _('Departamento')
        LOCAL = 'LOCAL', _('Local Comercial')
        OFICINA = 'OFICINA', _('Oficina')
        CASA = 'CASA', _('Casa')
        BODEGA = 'BODEGA', _('Bodega')

    edificio = models.ForeignKey(
        Edificio,
        on_delete=models.CASCADE,
        related_name='unidades',
        verbose_name=_('Edificio'),
    )
    numero = models.CharField(_('Número/identificador'), max_length=20)
    piso = models.PositiveSmallIntegerField(_('Piso'), default=0)
    tipo = models.CharField(
        _('Tipo'),
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.DEPARTAMENTO,
    )
    area_m2 = models.DecimalField(
        _('Área (m²)'),
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
    )
    inquilino = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='unidad_asignada',
        limit_choices_to={'role': 'INQUILINO'},
        verbose_name=_('Inquilino asignado'),
    )
    activo = models.BooleanField(_('Activa'), default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Unidad')
        verbose_name_plural = _('Unidades')
        ordering = ['edificio__nombre', 'piso', 'numero']
        constraints = [
            models.UniqueConstraint(
                fields=['edificio', 'numero'],
                name='unique_unidad_por_edificio',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.edificio.codigo}-{self.numero} ({self.get_tipo_display()})'

    @property
    def esta_ocupada(self) -> bool:
        return self.inquilino_id is not None

    @property
    def etiqueta_completa(self) -> str:
        """Cadena legible para mostrar en selects y tablas."""
        return f'{self.edificio.nombre} · {self.numero} (Piso {self.piso})'
