"""Servicio de notificaciones por correo electrónico SMTP.

Envía correos HTML en los eventos clave del ciclo de vida del ticket:
  1. Ticket creado           → Admin(s)
  2. Ticket aprobado         → Residente (agendar cita)
  3. Ticket aprobado         → Técnico (detalles del ticket)
  4. Cita agendada           → Técnico
  5. Ticket resuelto         → Residente
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from apps.accounts.models import CustomUser

logger = logging.getLogger(__name__)


def _get_admin_emails() -> list[str]:
    """Retorna lista de correos de todos los administradores activos."""
    return list(
        CustomUser.objects.filter(
            role=CustomUser.Roles.ADMIN,
            is_active=True,
        ).values_list('email', flat=True)
    )


def _send(*, subject: str, html_body: str, recipient_list: list[str]) -> bool:
    """Wrapper centralizado de envío con manejo de errores."""
    if not recipient_list:
        logger.warning("No hay destinatarios para el correo: %s", subject)
        return False
    try:
        send_mail(
            subject=subject,
            message='',  # texto plano vacío, se usa html_message
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_body,
            fail_silently=False,
        )
        logger.info("Correo enviado: '%s' → %s", subject, recipient_list)
        return True
    except Exception:
        logger.exception("Error enviando correo: '%s' → %s", subject, recipient_list)
        return False


# ── 1. Ticket creado → Admin(s) ─────────────────────────────────────────

def send_ticket_created_email(ticket_id: int) -> bool:
    """Notifica a los administradores que un residente creó un ticket."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'unidad', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de creación.", ticket_id)
        return False

    admin_emails = _get_admin_emails()
    if not admin_emails:
        return False

    html_body = render_to_string('emails/email_ticket_created.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })
    return _send(
        subject=f'🔔 Nuevo Ticket {ticket.codigo} — {ticket.get_prioridad_display()}',
        html_body=html_body,
        recipient_list=admin_emails,
    )


# ── 2. Ticket aprobado → Residente (agendar cita) ──────────────────────

def send_ticket_approved_resident_email(ticket_id: int) -> bool:
    """Notifica al residente que su ticket fue aprobado y debe agendar cita."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de aprobación (residente).", ticket_id)
        return False

    if not ticket.inquilino or not ticket.inquilino.email:
        return False

    html_body = render_to_string('emails/email_ticket_approved_resident.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })
    return _send(
        subject=f'✅ Tu reporte {ticket.codigo} fue aprobado — Agenda tu cita',
        html_body=html_body,
        recipient_list=[ticket.inquilino.email],
    )


# ── 3. Ticket aprobado → Técnico (detalles del ticket) ─────────────────

def send_ticket_approved_tech_email(ticket_id: int) -> bool:
    """Notifica al técnico que se le asignó un nuevo ticket."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de asignación (técnico).", ticket_id)
        return False

    if not ticket.tecnico or not ticket.tecnico.email:
        return False

    html_body = render_to_string('emails/email_ticket_approved_tech.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })
    return _send(
        subject=f'🔧 Nuevo ticket asignado: {ticket.codigo} — {ticket.get_prioridad_display()}',
        html_body=html_body,
        recipient_list=[ticket.tecnico.email],
    )


# ── 4. Cita agendada → Técnico ─────────────────────────────────────────

def send_ticket_scheduled_email(ticket_id: int) -> bool:
    """Notifica al técnico que el residente agendó la visita."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de agenda.", ticket_id)
        return False

    if not ticket.tecnico or not ticket.tecnico.email:
        return False

    html_body = render_to_string('emails/email_ticket_scheduled.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })

    fecha_str = ticket.fecha_programada.strftime('%d/%m/%Y') if ticket.fecha_programada else 'Sin fecha'
    return _send(
        subject=f'📅 Visita agendada: {ticket.codigo} — {fecha_str}',
        html_body=html_body,
        recipient_list=[ticket.tecnico.email],
    )



# ── 5. Ticket resuelto → Residente ─────────────────────────────────────

def send_ticket_resolved_email(ticket_id: int) -> bool:
    """Notifica al residente que su problema fue resuelto."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de resolución.", ticket_id)
        return False

    if not ticket.inquilino or not ticket.inquilino.email:
        return False

    html_body = render_to_string('emails/email_ticket_resolved.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })
    return _send(
        subject=f'🎉 Tu problema fue resuelto — {ticket.codigo}',
        html_body=html_body,
        recipient_list=[ticket.inquilino.email],
    )


# ── 6. Ticket resuelto → Admin(s) (cierre del ciclo) ───────────────────

def send_ticket_resolved_admin_email(ticket_id: int) -> bool:
    """Notifica a los administradores que el técnico cerró el ticket."""
    from apps.tickets.models import Ticket

    try:
        ticket = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad__edificio',
        ).get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("Ticket %d no encontrado para email de cierre (admin).", ticket_id)
        return False

    admin_emails = _get_admin_emails()
    if not admin_emails:
        return False

    html_body = render_to_string('emails/email_ticket_resolved_admin.html', {
        'ticket': ticket,
        'site_url': settings.SITE_URL,
    })
    tecnico_nombre = ticket.tecnico.get_full_name() if ticket.tecnico else 'Técnico'
    return _send(
        subject=f'✅ Ticket Cerrado {ticket.codigo} — {tecnico_nombre}',
        html_body=html_body,
        recipient_list=admin_emails,
    )