"""API de autenticación: JWT y recuperación de contraseña."""

from django.contrib.auth import login
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    EmailTokenObtainPairSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
)
from .services.password_reset import (
    PasswordResetError,
    confirm_password_reset,
    request_password_reset,
    verify_email_code,
)


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer


class PasswordResetRequestAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(serializer.validated_data['email'])
        return Response({
            'detail': (
                'Si el correo está registrado, recibirás un código de verificación en breve.'
            ),
        })


class PasswordResetVerifyAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            reset_token = verify_email_code(data['email'], data['code'])
        except PasswordResetError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'Correo verificado correctamente.',
            'reset_token': reset_token,
        })


class PasswordResetConfirmAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            user, tokens = confirm_password_reset(
                data['reset_token'],
                data['new_password'],
            )
        except PasswordResetError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user)
        return Response({
            'detail': 'Contraseña actualizada. Sesión iniciada.',
            'access': tokens['access'],
            'refresh': tokens['refresh'],
        })


# Re-export para urls
TokenRefreshAPIView = TokenRefreshView
