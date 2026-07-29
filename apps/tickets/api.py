import logging

from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notificacion, Ticket, TicketStatus
from .permissions import IsTicketParticipantOrAdmin
from .serializers import NotificacionSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notificaciones_list(request):
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
    Notificacion.objects.filter(
        usuario=request.user,
        leido=False
    ).update(leido=True)
    
    return Response({'status': 'ok'}, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def notificacion_marcar_leida(request, pk):
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


logger = logging.getLogger(__name__)


class TicketReportPDFView(APIView):

    permission_classes = [IsAuthenticated, IsTicketParticipantOrAdmin]

    def get_object(self):
        from django.shortcuts import get_object_or_404
        ticket = get_object_or_404(
            Ticket.objects.select_related(
                'inquilino', 'tecnico', 'unidad', 'unidad__edificio',
            ),
            pk=self.kwargs['pk'],
        )
        self.check_object_permissions(self.request, ticket)
        return ticket

    def get(self, request, pk):
        ticket = self.get_object()

        if ticket.estado != TicketStatus.RESUELTO:
            return Response(
                {'detail': 'Solo se pueden generar reportes de tickets resueltos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from .services.pdf_service import generate_ticket_pdf
            is_audit = getattr(request.user, 'is_admin', False) or request.user.is_superuser
            pdf_bytes = generate_ticket_pdf(ticket, is_audit=is_audit)
        except Exception:
            logger.exception("Error generando PDF para ticket %s", ticket.codigo)
            return Response(
                {'detail': 'Error interno al generar el reporte PDF.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="Reporte_{ticket.codigo}.pdf"'
        )
        return response

