import secrets
from datetime import date, datetime, time, timedelta

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
    max_carga_trabajo = models.PositiveIntegerField(
        _('Límite de carga de trabajo'),
        default=10,
        help_text=_(
            'Máximo de puntos de carga activa (ALTA=3, MEDIA=2, BAJA=1). '
            'Solo aplica para técnicos.'
        ),
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

    # ── Carga de trabajo (solo técnicos) ───────────────────────────────

    # Pesos de prioridad para el cálculo de carga
    PRIORITY_WEIGHTS: dict[str, int] = {
        'ALTA': 3,
        'MEDIA': 2,
        'BAJA': 1,
    }

    _ESTADOS_ACTIVOS = ('ASIGNADO', 'EN_CAMINO', 'EN_PROGRESO')

    @property
    def carga_trabajo_actual(self) -> int:
        """Suma de pesos de prioridad de tickets activos asignados."""
        if not self.is_tecnico:
            return 0
        from django.db.models import Case, IntegerField, Sum, Value, When
        resultado = self.tickets_asignados.filter(
            estado__in=self._ESTADOS_ACTIVOS,
        ).aggregate(
            carga=Sum(
                Case(
                    When(prioridad='ALTA', then=Value(3)),
                    When(prioridad='MEDIA', then=Value(2)),
                    When(prioridad='BAJA', then=Value(1)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
        )
        return resultado['carga'] or 0

    @property
    def carga_disponible(self) -> int:
        """Puntos de carga que aún puede aceptar el técnico."""
        return max(0, self.max_carga_trabajo - self.carga_trabajo_actual)

    def puede_aceptar_ticket(self, prioridad: str) -> bool:
        """True si el técnico tiene capacidad para un ticket de esta prioridad."""
        peso = self.PRIORITY_WEIGHTS.get(prioridad, 1)
        return self.carga_disponible >= peso

    # ── Especialidades múltiples (M2M) ──────────────────────────────────

    @property
    def especialidades_list(self) -> list[str]:
        """Lista de especialidades del técnico (desde tabla M2M)."""
        if not self.is_tecnico:
            return []
        return list(
            self.especialidades_tecnico
            .values_list('especialidad', flat=True)
        )

    @property
    def especialidades_display(self) -> str:
        """Texto legible de especialidades separadas por coma."""
        if not self.is_tecnico:
            return ''
        items = self.especialidades_tecnico.all()
        if not items.exists():
            # Fallback al campo legacy
            return self.get_especialidad_display() if self.especialidad else ''
        return ', '.join(
            item.get_especialidad_display() for item in items
        )

    def tiene_especialidad(self, categoria: str) -> bool:
        """Verifica si el técnico tiene una especialidad específica."""
        if self.especialidades_tecnico.filter(especialidad=categoria).exists():
            return True
        # Fallback al campo legacy
        return self.especialidad == categoria

    # ── Disponibilidad horaria ──────────────────────────────────────────

    def esta_disponible_ahora(self) -> bool:
        """Verifica si el técnico está en su horario de trabajo ahora."""
        if not self.is_tecnico:
            return False
        ahora = timezone.localtime(timezone.now())
        return self._en_horario(ahora.weekday(), ahora.time())

    def esta_disponible_en(self, fecha: date, hora: time) -> bool:
        """Verifica si el técnico trabaja en ese día y hora."""
        if not self.is_tecnico:
            return False
        dia_semana = fecha.weekday()
        return self._en_horario(dia_semana, hora)

    def _en_horario(self, dia_semana: int, hora: time) -> bool:
        """Verifica si una hora cae dentro del horario semanal del técnico."""
        return self.horarios.filter(
            dia_semana=dia_semana,
            hora_inicio__lte=hora,
            hora_fin__gt=hora,
        ).exists()

    def get_horario_dia(self, dia_semana: int):
        """Retorna los bloques de horario para un día de la semana."""
        return self.horarios.filter(dia_semana=dia_semana).order_by('hora_inicio')

    def get_horario_fecha(self, fecha: date):
        """Retorna los bloques de horario para una fecha específica."""
        return self.get_horario_dia(fecha.weekday())

    def proximo_horario_disponible(self, desde: datetime | None = None) -> dict | None:
        """Encuentra el próximo bloque horario disponible en los próximos 7 días.

        Returns:
            dict con 'fecha', 'hora_inicio', 'hora_fin' o None si no hay disponibilidad.
        """
        if not self.is_tecnico:
            return None
        if desde is None:
            desde = timezone.localtime(timezone.now())

        for offset in range(8):  # Hoy + 7 días adelante
            fecha = (desde + timedelta(days=offset)).date() if offset > 0 else desde.date()
            bloques = self.get_horario_dia(fecha.weekday())
            for bloque in bloques:
                hora_inicio = bloque.hora_inicio
                # Si es hoy y la hora ya pasó, saltar
                if offset == 0 and hora_inicio <= desde.time():
                    hora_inicio = desde.time()
                    # Verificar que aún quede tiempo en el bloque
                    if hora_inicio >= bloque.hora_fin:
                        continue
                return {
                    'fecha': fecha,
                    'hora_inicio': bloque.hora_inicio,
                    'hora_fin': bloque.hora_fin,
                }
        return None


class TecnicoEspecialidad(models.Model):
    """Relación M2M entre técnico y especialidades.

    Permite que un técnico tenga múltiples áreas de competencia,
    con una marcada como principal.
    """

    tecnico = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='especialidades_tecnico',
        verbose_name=_('Técnico'),
    )
    especialidad = models.CharField(
        _('Especialidad'),
        max_length=20,
        choices=CustomUser.Especialidad.choices,
    )
    es_principal = models.BooleanField(
        _('Es principal'),
        default=False,
        help_text=_('Marca esta especialidad como la principal del técnico.'),
    )

    class Meta:
        verbose_name = _('Especialidad del Técnico')
        verbose_name_plural = _('Especialidades de Técnicos')
        unique_together = ('tecnico', 'especialidad')
        ordering = ['-es_principal', 'especialidad']

    def __str__(self) -> str:
        principal = ' ★' if self.es_principal else ''
        return f'{self.tecnico.get_full_name()} — {self.get_especialidad_display()}{principal}'


class HorarioTrabajo(models.Model):
    """Horario de trabajo semanal de un técnico.

    Define bloques de disponibilidad por día de la semana.
    Un técnico puede tener múltiples bloques por día
    (ej. mañana y tarde con pausa de almuerzo).
    """

    class DiaSemana(models.IntegerChoices):
        LUNES = 0, _('Lunes')
        MARTES = 1, _('Martes')
        MIERCOLES = 2, _('Miércoles')
        JUEVES = 3, _('Jueves')
        VIERNES = 4, _('Viernes')
        SABADO = 5, _('Sábado')
        DOMINGO = 6, _('Domingo')

    DIAS_LABELS = {
        0: 'Lun', 1: 'Mar', 2: 'Mié',
        3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom',
    }

    tecnico = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='horarios',
        limit_choices_to={'role': 'TECNICO'},
        verbose_name=_('Técnico'),
    )
    dia_semana = models.IntegerField(
        _('Día de la semana'),
        choices=DiaSemana.choices,
    )
    hora_inicio = models.TimeField(_('Hora de inicio'))
    hora_fin = models.TimeField(_('Hora de fin'))

    class Meta:
        verbose_name = _('Horario de Trabajo')
        verbose_name_plural = _('Horarios de Trabajo')
        unique_together = ('tecnico', 'dia_semana', 'hora_inicio')
        ordering = ['dia_semana', 'hora_inicio']
        indexes = [
            models.Index(fields=['tecnico', 'dia_semana']),
        ]

    def __str__(self) -> str:
        dia = self.DIAS_LABELS.get(self.dia_semana, str(self.dia_semana))
        return (
            f'{self.tecnico.get_full_name()} · {dia} '
            f'{self.hora_inicio.strftime("%H:%M")}–{self.hora_fin.strftime("%H:%M")}'
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError(
                _('La hora de inicio debe ser anterior a la hora de fin.')
            )

    @property
    def duracion_horas(self) -> float:
        """Duración del bloque en horas."""
        inicio = datetime.combine(date.today(), self.hora_inicio)
        fin = datetime.combine(date.today(), self.hora_fin)
        return (fin - inicio).total_seconds() / 3600


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
