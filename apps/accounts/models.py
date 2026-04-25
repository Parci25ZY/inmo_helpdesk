from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

class CustomUser(AbstractUser):
    """
    Modelo de usuario personalizado para el sistema InmoHelpdesk.
    Centraliza la identidad de Inquilinos y Técnicos.
    """
    class Roles(models.TextChoices):
        INQUILINO = 'INQUILINO', _('Inquilino')
        TECNICO = 'TECNICO', _('Técnico')

    # Campos adicionales con nombres descriptivos (verbose_name)
    rol = models.CharField(
        _("Rol del usuario"),
        max_length=15,
        choices=Roles.choices,
        default=Roles.INQUILINO,
        help_text=_("Define el nivel de acceso al sistema.")
    )
    
    telefono = models.CharField(
        _("Número de teléfono"),
        max_length=20,
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = _("Usuario")
        verbose_name_plural = _("Usuarios")
        ordering = ['-date_joined']

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} ({self.get_rol_display()})"

    @property
    def is_tecnico(self) -> bool:
        """Helper para verificar rápidamente si el usuario es técnico."""
        return self.rol == self.Roles.TECNICO

    @property
    def is_inquilino(self) -> bool:
        """Helper para verificar rápidamente si el usuario es inquilino."""
        return self.rol == self.Roles.INQUILINO