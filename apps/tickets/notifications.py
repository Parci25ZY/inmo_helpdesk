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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_ticket_aprobado(self, ticket_id: int) -> bool:
    """Envía un correo directo al inquilino cuando el administrador aprueba su ticket."""
    from apps.tickets.models import Ticket
    try:
        ticket = Ticket.objects.select_related('inquilino').get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para notificación de aprobación.", ticket_id)
        return False

    asunto = f"Ticket Aprobado: {ticket.codigo}"
    mensaje = (
        f"Hola {ticket.inquilino.get_full_name()},\n\n"
        f"Tu reporte '{ticket.titulo}' ha sido aprobado por el administrador.\n"
        f"El siguiente paso es seleccionar el horario de visita para el soporte técnico.\n\n"
        f"Puedes agendar tu cita aquí: {settings.SITE_URL}/tickets/{ticket.pk}/\n"
    )

    try:
        send_mail(
            subject=asunto,
            message=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ticket.inquilino.email],
            fail_silently=False,
        )
        logger.info("Notificación de aprobación de ticket enviada a %s.", ticket.inquilino.email)
        return True
    except Exception as exc:
        logger.error("Fallo al enviar correo de aprobación para %s: %s", ticket.codigo, exc)
        raise self.retry(exc=exc)

