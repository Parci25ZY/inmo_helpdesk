"""Notificaciones de tickets hacia sistemas externos (n8n)."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def notify_nuevo_ticket(ticket) -> bool:
    """Envía un webhook a n8n cuando un inquilino crea un ticket.

    n8n recibe el payload y envía el correo de alerta al administrador.
    Si n8n no está disponible, registra el fallo en el log y continúa
    sin interrumpir el flujo del usuario.
    """
    webhook_url = getattr(settings, 'N8N_WEBHOOK_URL', '').strip()
    if not webhook_url:
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
    return False
