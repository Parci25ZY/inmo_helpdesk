"""Tokens JWT personalizados (simplejwt)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken, Token

User = get_user_model()


class PasswordResetToken(Token):
    """JWT de corta duración para confirmar el cambio de contraseña."""

    token_type = 'password_reset'
    lifetime = timedelta(minutes=30)

    @classmethod
    def for_user(cls, user) -> 'PasswordResetToken':
        token = cls()
        token['user_id'] = user.pk
        token['email'] = user.email
        token['purpose'] = 'password_reset'
        return token

    @classmethod
    def get_user(cls, token_str: str):
        token = cls(token_str)
        user_id = token.get('user_id')
        if not user_id or token.get('purpose') != 'password_reset':
            raise ValueError('Token inválido')
        return User.objects.get(pk=user_id, is_active=True)


def issue_auth_tokens(user) -> dict[str, str]:
    """Emite par access + refresh para el usuario."""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }
