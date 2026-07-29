from rest_framework import serializers

from .models import Notificacion


class NotificacionSerializer(serializers.ModelSerializer):
    
    url_ticket = serializers.SerializerMethodField()
    tiempo_relativo = serializers.SerializerMethodField()
    codigo_ticket = serializers.SerializerMethodField()
    estado_ticket = serializers.SerializerMethodField()

    class Meta:
        model = Notificacion
        fields = [
            'id',
            'mensaje',
            'descripcion',
            'tipo_alerta',
            'leido',
            'creado_en',
            'url_ticket',
            'tiempo_relativo',
            'codigo_ticket',
            'estado_ticket',
        ]

    def get_estado_ticket(self, obj: Notificacion) -> str | None:
        return obj.ticket.get_estado_display() if obj.ticket else None

    def get_url_ticket(self, obj: Notificacion) -> str | None:
        if obj.ticket:
            from django.urls import reverse
            return reverse('ticket_detail', kwargs={'pk': obj.ticket.pk})
        return None

    def get_codigo_ticket(self, obj: Notificacion) -> str | None:
        return obj.ticket.codigo if obj.ticket else None

    def get_tiempo_relativo(self, obj: Notificacion) -> str:
        from django.utils import timezone
        
        local_time = timezone.localtime(obj.creado_en)
        return local_time.strftime("%d/%m %H:%M")
