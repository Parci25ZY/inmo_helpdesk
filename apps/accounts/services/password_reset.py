"""Servicio de recuperación de contraseña con verificación por correo."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils.translation import gettext as _

from apps.accounts.models import EmailVerificationCode
from apps.accounts.tokens import PasswordResetToken, issue_auth_tokens

User = get_user_model()


class PasswordResetError(Exception):
    pass


def request_password_reset(email: str) -> None:
    """Genera código y envía correo. No revela si el email existe."""
    email = email.strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=True).first()

    if user:
        record = EmailVerificationCode.create_for_email(
            email=email,
            user=user,
            purpose=EmailVerificationCode.Purpose.PASSWORD_RESET,
        )
        _send_verification_email(user, record.code)

    # Siempre mismo mensaje público (evita enumeración de cuentas).


def verify_email_code(email: str, code: str) -> str:
    """Valida código de 6 dígitos y retorna JWT de reset."""
    email = email.strip().lower()
    code = code.strip()

    record = (
        EmailVerificationCode.objects
        .filter(
            email__iexact=email,
            code=code,
            purpose=EmailVerificationCode.Purpose.PASSWORD_RESET,
            is_used=False,
            verified_at__isnull=True,
        )
        .select_related('user')
        .order_by('-created_at')
        .first()
    )

    if not record or record.is_expired or not record.user:
        raise PasswordResetError(_('Código inválido o expirado.'))

    record.mark_verified()
    return str(PasswordResetToken.for_user(record.user))


def confirm_password_reset(reset_token: str, new_password: str) -> tuple[User, dict[str, str]]:
    """Cambia contraseña con JWT de reset y emite tokens de sesión API."""
    try:
        user = PasswordResetToken.get_user(reset_token)
    except Exception as exc:
        raise PasswordResetError(_('El enlace de recuperación no es válido o expiró.')) from exc

    user.set_password(new_password)
    user.save(update_fields=['password'])

    EmailVerificationCode.objects.filter(
        user=user,
        purpose=EmailVerificationCode.Purpose.PASSWORD_RESET,
        is_used=False,
    ).update(is_used=True)

    return user, issue_auth_tokens(user)


def _send_verification_email(user: User, code: str) -> None:
    subject = _('InmoHelpdesk — Código de recuperación de contraseña')
    message = _(
        'Hola {name},\n\n'
        'Tu código de verificación es: {code}\n\n'
        'Válido por 15 minutos. Si no solicitaste esto, ignora este mensaje.\n\n'
        '— InmoHelpdesk'
    ).format(name=user.first_name or user.email, code=code)

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
