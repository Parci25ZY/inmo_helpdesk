"""Serializers DRF para la API del chatbot."""

from __future__ import annotations

from rest_framework import serializers

from apps.ai_agent.models import ChatMessage, ChatSession


class ChatMessageSerializer(serializers.ModelSerializer):
    chunks_usados_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'uuid',
            'rol',
            'contenido',
            'estado_proceso',
            'metadata',
            'chunks_usados_count',
            'creado_en',
        ]
        read_only_fields = fields

    def get_chunks_usados_count(self, obj: ChatMessage) -> int:
        return obj.chunks_usados.count()


class ChatSessionSerializer(serializers.ModelSerializer):
    mensajes = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatSession
        fields = [
            'uuid',
            'titulo',
            'estado',
            'mensajes',
            'creado_en',
            'actualizado_en',
        ]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    contenido = serializers.CharField(max_length=4000, trim_whitespace=True)

    def validate_contenido(self, value: str) -> str:
        if len(value.strip()) < 2:
            raise serializers.ValidationError('El mensaje es demasiado corto.')
        return value.strip()
