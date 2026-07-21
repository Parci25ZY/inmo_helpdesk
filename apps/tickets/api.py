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


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def notificacion_marcar_leida(request, pk):
    """Marca una sola notificación como leída y retorna el nuevo conteo."""
    updated = Notificacion.objects.filter(
        pk=pk,
        usuario=request.user,
        leido=False,
    ).update(leido=True)

    unread_count = Notificacion.objects.filter(
        usuario=request.user,
        leido=False,
    ).count()

    return Response({
        'status': 'ok',
        'updated': bool(updated),
        'unread_count': unread_count,
    }, status=status.HTTP_200_OK)
