"""API REST del chatbot (DRF)."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_agent.models import ChatMessage, ChatSession
from apps.ai_agent.serializers import (
    ChatMessageSerializer,
    ChatSessionSerializer,
    SendMessageSerializer,
)
from apps.ai_agent.tasks import process_chat_message


class ActiveChatSessionView(APIView):
    """Obtiene o crea la sesión activa del usuario autenticado."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sesion = (
            ChatSession.objects
            .filter(usuario=request.user, estado=ChatSession.Estado.ACTIVA)
            .prefetch_related('mensajes')
            .first()
        )
        if not sesion:
            sesion = ChatSession.objects.create(usuario=request.user)
        serializer = ChatSessionSerializer(sesion)
        return Response(serializer.data)

    def post(self, request):
        """Cierra sesión actual y crea una nueva."""
        ChatSession.objects.filter(
            usuario=request.user,
            estado=ChatSession.Estado.ACTIVA,
        ).update(estado=ChatSession.Estado.CERRADA)
        sesion = ChatSession.objects.create(usuario=request.user)
        return Response(
            ChatSessionSerializer(sesion).data,
            status=status.HTTP_201_CREATED,
        )


class ChatMessageSendView(APIView):
    """Envía un mensaje del usuario y encola la respuesta del asistente."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contenido = serializer.validated_data['contenido']

        sesion = (
            ChatSession.objects
            .filter(usuario=request.user, estado=ChatSession.Estado.ACTIVA)
            .first()
        )
        if not sesion:
            sesion = ChatSession.objects.create(usuario=request.user)

        user_msg = ChatMessage.objects.create(
            sesion=sesion,
            rol=ChatMessage.Rol.USUARIO,
            contenido=contenido,
            estado_proceso=ChatMessage.EstadoProceso.COMPLETADO,
        )

        asistente_msg = ChatMessage.objects.create(
            sesion=sesion,
            rol=ChatMessage.Rol.ASISTENTE,
            contenido='',
            estado_proceso=ChatMessage.EstadoProceso.PENDIENTE,
        )

        sesion.actualizado_en = timezone.now()
        sesion.save(update_fields=['actualizado_en'])

        try:
            process_chat_message.delay(asistente_msg.pk)
        except Exception:
            from apps.ai_agent.services.chat import process_user_message
            process_user_message(asistente_msg)

        return Response(
            {
                'user_message': ChatMessageSerializer(user_msg).data,
                'assistant_message': ChatMessageSerializer(asistente_msg).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ChatMessageDetailView(APIView):
    """Consulta el estado de un mensaje (polling)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, uuid):
        mensaje = ChatMessage.objects.select_related('sesion').filter(
            uuid=uuid,
            sesion__usuario=request.user,
        ).first()
        if not mensaje:
            return Response({'detail': 'No encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(ChatMessageSerializer(mensaje).data)
