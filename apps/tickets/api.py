from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notificacion
from .serializers import NotificacionSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notificaciones_list(request):
    """Lista las últimas 5 notificaciones no leídas del usuario."""
    # Count total unread
    unread_count = Notificacion.objects.filter(
        usuario=request.user,
        leido=False
    ).count()

    notificaciones = Notificacion.objects.filter(
        usuario=request.user,
        leido=False
    ).order_by('-creado_en')[:5]
    
    serializer = NotificacionSerializer(notificaciones, many=True)
    return Response({
        'count': unread_count,
        'results': serializer.data
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notificaciones_marcar_leidas(request):
    """Marca todas las notificaciones del usuario como leídas."""
    Notificacion.objects.filter(
        usuario=request.user,
        leido=False
    ).update(leido=True)
    
    return Response({'status': 'ok'}, status=status.HTTP_200_OK)
