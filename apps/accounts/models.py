import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('El correo electrónico es obligatorio'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', CustomUser.Roles.ADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('El superusuario debe tener is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('El superusuario debe tener is_superuser=True.'))

        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', _('Administrador')
        INQUILINO = 'INQUILINO', _('Residente')
        TECNICO = 'TECNICO', _('Técnico')

    class Especialidad(models.TextChoices):
        PLOMERIA = 'PLOMERIA', _('Plomería')
        ELECTRICIDAD = 'ELECTRICIDAD', _('Electricidad')
        INFRAESTRUCTURA = 'INFRAESTRUCTURA', _('Infraestructura')
        LIMPIEZA = 'LIMPIEZA', _('Limpieza')
        SEGURIDAD = 'SEGURIDAD', _('Seguridad')
        OTRO = 'OTRO', _('Otro')

    email = models.EmailField(_('Correo Electrónico'), unique=True)
    first_name = models.CharField(_('Nombres'), max_length=150, blank=True)
    last_name = models.CharField(_('Apellidos'), max_length=150, blank=True)
    phone = models.CharField(_('Teléfono'), max_length=20, blank=True, null=True)
    role = models.CharField(
        _('Rol'),
        max_length=20,
        choices=Roles.choices,
        default=Roles.INQUILINO,
    )
    especialidad = models.CharField(
        _('Especialidad'),
        max_length=20,
        choices=Especialidad.choices,
        blank=True,
        default='',
        help_text=_('Solo aplica para técnicos. Define su área de competencia.'),
    )
    is_active = models.BooleanField(_('Activo'), default=True)
    is_staff = models.BooleanField(_('Staff'), default=False)
    date_joined = models.DateTimeField(_('Fecha de Creación'), auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = _('Usuario')
        verbose_name_plural = _('Usuarios')
        ordering = ['-date_joined']

    def __str__(self) -> str:
        return f'{self.get_full_name()} ({self.get_role_display()})'

    def get_full_name(self) -> str:
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email

    @property
    def is_admin(self) -> bool:
        return self.role == self.Roles.ADMIN or self.is_superuser

    @property
    def is_inquilino(self) -> bool:
        return self.role == self.Roles.INQUILINO

    @property
    def is_residente(self) -> bool:
        """Alias de is_inquilino para la nueva terminología."""
        return self.is_inquilino

    @property
    def is_tecnico(self) -> bool:
        return self.role == self.Roles.TECNICO


class EmailVerificationCode(models.Model):
    """Código de verificación enviado al correo (recuperación de contraseña)."""

    class Purpose(models.TextChoices):
        PASSWORD_RESET = 'PASSWORD_RESET', _('Recuperación de contraseña')

    email = models.EmailField(_('Correo'))
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='verification_codes',
        null=True,
        blank=True,
    )
    code = models.CharField(_('Código'), max_length=6)
    purpose = models.CharField(
        _('Propósito'),
        max_length=20,
        choices=Purpose.choices,
        default=Purpose.PASSWORD_RESET,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('Código de verificación')
        verbose_name_plural = _('Códigos de verificación')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'purpose', 'code']),
        ]

    def __str__(self) -> str:
        return f'{self.email} · {self.code}'

    @classmethod
    def generate_code(cls) -> str:
        return f'{secrets.randbelow(1_000_000):06d}'

    @classmethod
    def create_for_email(cls, email: str, user: CustomUser | None, purpose: str) -> 'EmailVerificationCode':
        cls.objects.filter(
            email__iexact=email,
            purpose=purpose,
            is_used=False,
            verified_at__isnull=True,
        ).update(is_used=True)

        return cls.objects.create(
            email=email.lower(),
            user=user,
            code=cls.generate_code(),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def mark_verified(self) -> None:
        self.verified_at = timezone.now()
        self.save(update_fields=['verified_at'])

    def mark_used(self) -> None:
        self.is_used = True
        self.save(update_fields=['is_used'])
