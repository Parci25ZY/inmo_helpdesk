"""Notificaciones de tickets hacia sistemas externos (n8n)."""

import logging

import requests
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def notify_nuevo_ticket(self, ticket_id: int) -> bool:
    """Envía un webhook a n8n cuando un inquilino crea un ticket.

    n8n recibe el payload y envía el correo de alerta al administrador.
    Se ejecuta como task Celery para no bloquear la respuesta al usuario.
    Si n8n no está disponible, registra el fallo en el log y continúa
    sin interrumpir el flujo del usuario.
    """
    webhook_url = getattr(settings, 'N8N_WEBHOOK_URL', '').strip()
    if not webhook_url:
        return False

    from apps.tickets.models import Ticket
    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'unidad', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para notificación n8n.", ticket_id)
        return False

    payload = {
        'ticket_id': ticket.pk,
        'codigo': ticket.codigo,
        'titulo': ticket.titulo,
        'descripcion': ticket.descripcion[:400],
        'prioridad': ticket.get_prioridad_display(),
        'inquilino_nombre': ticket.inquilino.get_full_name(),
        'inquilino_email': ticket.inquilino.email,
        'unidad': (
            f"{ticket.unidad.edificio.nombre} · "
            f"Unidad #{ticket.unidad.numero} · "
            f"Piso {ticket.unidad.piso}"
        ),
        'url_ticket': f"{settings.SITE_URL}/tickets/{ticket.pk}/",
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=4)
        response.raise_for_status()
        logger.info("Notificación n8n enviada para ticket %s.", ticket.codigo)
        return True
    except requests.exceptions.ConnectionError:
        logger.warning("n8n no disponible — notificación omitida para %s.", ticket.codigo)
    except requests.exceptions.Timeout:
        logger.warning("n8n timeout — notificación omitida para %s.", ticket.codigo)
    except Exception as exc:
        logger.warning("n8n error (%s) — notificación omitida para %s.", exc, ticket.codigo)
        raise self.retry(exc=exc)
    return False
