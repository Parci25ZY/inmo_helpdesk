"""Serializers DRF para autenticación JWT y recuperación de contraseña."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login JWT usando correo electrónico como identificador."""

    username_field = User.USERNAME_FIELD


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    def validate_code(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError('El código debe contener solo números.')
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)
    new_password_confirm = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': 'Las contraseñas no coinciden.',
            })
        validate_password(attrs['new_password'])
        return attrs
