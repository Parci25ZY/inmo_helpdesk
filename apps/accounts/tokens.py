"""Tokens JWT personalizados (simplejwt)."""

import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, Token

User = get_user_model()


def _password_fingerprint(user) -> str:
    """Hash corto del password hash del usuario para incluir en claims JWT.

    Cuando el usuario cambia su contraseña, el fingerprint cambia y
    cualquier token emitido anteriormente deja de ser válido.
    """
    return hashlib.sha256(user.password.encode()).hexdigest()[:16]


class PasswordResetToken(Token):
    """JWT de corta duración para confirmar el cambio de contraseña.

    Incluye un fingerprint del hash de contraseña actual del usuario.
    Si la contraseña cambia antes de usar el token, éste se invalida
    automáticamente.
    """

    token_type = 'password_reset'
    lifetime = timedelta(minutes=30)

    @classmethod
    def for_user(cls, user) -> 'PasswordResetToken':
        token = cls()
        token['user_id'] = user.pk
        token['email'] = user.email
        token['purpose'] = 'password_reset'
        token['pwd_fp'] = _password_fingerprint(user)
        return token

    @classmethod
    def get_user(cls, token_str: str):
        token = cls(token_str)
        user_id = token.get('user_id')
        if not user_id or token.get('purpose') != 'password_reset':
            raise ValueError('Token inválido')
        user = User.objects.get(pk=user_id, is_active=True)
        # Verificar que la contraseña no haya cambiado desde la emisión
        if token.get('pwd_fp') != _password_fingerprint(user):
            raise ValueError(
                'Este enlace ya fue utilizado o la contraseña fue cambiada.'
            )
        return user


def issue_auth_tokens(user) -> dict[str, str]:
    """Emite par access + refresh para el usuario."""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }

