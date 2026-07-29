"""Notificaciones nativas de tickets por correo electrónico mediante Celery."""

import logging
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_nuevo_ticket(self, ticket_id: int) -> bool:
    """Envía un correo directo al administrador cuando se crea un ticket."""
    from apps.tickets.models import Ticket
    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'unidad', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para notificación por correo.", ticket_id)
        return False

    asunto = f"Nuevo Ticket Creado: {ticket.codigo}"
    mensaje = (
        f"Hola Administrador,\n\n"
        f"Se ha registrado un nuevo reporte de soporte:\n\n"
        f"Código: {ticket.codigo}\n"
        f"Título: {ticket.titulo}\n"
        f"Prioridad: {ticket.get_prioridad_display()}\n"
        f"Inquilino: {ticket.inquilino.get_full_name()}\n"
        f"Unidad: {ticket.unidad.edificio.nombre} - {ticket.unidad.numero}\n\n"
        f"Detalles:\n{ticket.descripcion[:400]}\n\n"
        f"Puedes gestionarlo en: {settings.SITE_URL}/tickets/{ticket.pk}/\n"
    )

    try:
        send_mail(
            subject=asunto,
            message=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.EMAIL_HOST_USER],  # Correo del admin
            fail_silently=False,
        )
        logger.info("Notificación de correo enviada para nuevo ticket %s.", ticket.codigo)
        return True
    except Exception as exc:
        logger.error("Fallo al enviar correo para ticket %s: %s", ticket.codigo, exc)
        raise self.retry(exc=exc)


# Nota: existía aquí notify_ticket_aprobado (correo de texto plano al
# residente al aprobar) — se eliminó porque duplicaba exactamente el mismo
# aviso que ya envía send_ticket_approved_resident_email (HTML), disparado
# desde el mismo punto en TicketValidateView.form_valid(). El residente
# recibía dos correos distintos por una sola aprobación.

