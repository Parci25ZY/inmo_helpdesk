
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.accounts.models import CustomUser

from apps.tickets.models import Notificacion, Ticket, TicketStatus, TipoAlerta

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_admins():
    return CustomUser.objects.filter(
        role=CustomUser.Roles.ADMIN,
        is_active=True,
    )


def _create_for_users(users, *, ticket, mensaje, descripcion='', tipo_alerta=TipoAlerta.INFO):
    notificaciones = []
    for user in users:
        notificaciones.append(Notificacion(
            usuario=user,
            ticket=ticket,
            mensaje=mensaje,
            descripcion=descripcion,
            tipo_alerta=tipo_alerta,
        ))
    if notificaciones:
        Notificacion.objects.bulk_create(notificaciones)
    return notificaciones




def notify_ticket_created(ticket: Ticket):
    admins = _get_admins()
    _create_for_users(
        admins,
        ticket=ticket,
        mensaje=f'Nuevo ticket — {ticket.get_prioridad_display()}',
        descripcion=ticket.descripcion[:200] if ticket.descripcion else '',
        tipo_alerta=TipoAlerta.WARNING,
    )


def notify_transition(ticket: Ticket, *, estado_anterior: str, nuevo_estado: str, actor=None):
    handlers = {
        TicketStatus.PENDIENTE_VALIDACION: _on_pendiente_validacion,
        TicketStatus.APROBADO: _on_aprobado,
        TicketStatus.ASIGNADO: _on_asignado,
        TicketStatus.EN_CAMINO: _on_en_camino,
        TicketStatus.EN_PROGRESO: _on_en_progreso,
        TicketStatus.RESUELTO: _on_resuelto,
        TicketStatus.CANCELADO: _on_cancelado,
    }
    handler = handlers.get(nuevo_estado)
    if handler:
        try:
            handler(ticket, actor=actor)
        except Exception:
            logger.exception(
                "Error creando notificación para %s → %s",
                estado_anterior, nuevo_estado,
            )


def notify_new_message(ticket: Ticket, *, autor):
    destinatarios = []

    if hasattr(autor, 'role'):
        if autor.role == CustomUser.Roles.INQUILINO:
            if ticket.tecnico:
                destinatarios.append(ticket.tecnico)
            destinatarios.extend(list(_get_admins()))
        elif autor.role == CustomUser.Roles.TECNICO:
            if ticket.inquilino:
                destinatarios.append(ticket.inquilino)
            destinatarios.extend(list(_get_admins()))
        else:
            if ticket.inquilino:
                destinatarios.append(ticket.inquilino)
            if ticket.tecnico:
                destinatarios.append(ticket.tecnico)

    seen = set()
    unicos = []
    for d in destinatarios:
        if d.pk not in seen and d.pk != autor.pk:
            seen.add(d.pk)
            unicos.append(d)

    if unicos:
        _create_for_users(
            unicos,
            ticket=ticket,
            mensaje=f'Nuevo mensaje en ticket',
            descripcion=f'{autor.get_full_name()} dejó un mensaje.',
            tipo_alerta=TipoAlerta.INFO,
        )




def _on_pendiente_validacion(ticket: Ticket, *, actor=None):
    admins = _get_admins()
    if actor:
        admins = admins.exclude(pk=actor.pk)
    _create_for_users(
        admins,
        ticket=ticket,
        mensaje='Requiere tu validación',
        descripcion=ticket.descripcion[:200] if ticket.descripcion else '',
        tipo_alerta=TipoAlerta.WARNING,
    )

    try:
        from apps.tickets.notifications import notify_nuevo_ticket
        notify_nuevo_ticket.delay(ticket.pk)
    except Exception:
        logger.exception('Error encolando correo de texto de nuevo ticket %s.', ticket.pk)

    try:
        from apps.tickets.services.email_service import send_ticket_created_email
        send_ticket_created_email(ticket.pk)
    except Exception:
        logger.exception('Error enviando correo HTML de nuevo ticket %s.', ticket.pk)


def _on_aprobado(ticket: Ticket, *, actor=None):
    if ticket.inquilino:
        _create_for_users(
            [ticket.inquilino],
            ticket=ticket,
            mensaje='Aprobado — Agenda tu visita',
            descripcion='Tu reporte fue validado. Selecciona un horario para la visita del técnico.',
            tipo_alerta=TipoAlerta.SUCCESS,
        )


def _on_asignado(ticket: Ticket, *, actor=None):
    destinatarios = []

    if ticket.tecnico:
        destinatarios.append(ticket.tecnico)

    if actor and hasattr(actor, 'role') and actor.role == CustomUser.Roles.INQUILINO:
        destinatarios.extend(list(_get_admins()))
        tipo = TipoAlerta.INFO
        msg = f'Auto-asignado a {ticket.tecnico.get_full_name() if ticket.tecnico else "técnico"}'
    else:
        tipo = TipoAlerta.INFO
        msg = 'Nuevo trabajo asignado'

    seen = set()
    unicos = []
    for d in destinatarios:
        if d.pk not in seen and (actor is None or d.pk != actor.pk):
            seen.add(d.pk)
            unicos.append(d)

    if unicos:
        hora = ''
        if ticket.hora_programada_inicio:
            hora = f' · {ticket.hora_programada_inicio.strftime("%H:%M")}'
        _create_for_users(
            unicos,
            ticket=ticket,
            mensaje=msg,
            descripcion=f'{ticket.fecha_programada}{hora}' if ticket.fecha_programada else '',
            tipo_alerta=tipo,
        )


def _on_en_camino(ticket: Ticket, *, actor=None):
    if ticket.inquilino:
        tecnico_nombre = ticket.tecnico.get_full_name() if ticket.tecnico else 'El técnico'
        _create_for_users(
            [ticket.inquilino],
            ticket=ticket,
            mensaje='Técnico en camino',
            descripcion=f'{tecnico_nombre} se dirige a tu unidad.',
            tipo_alerta=TipoAlerta.INFO,
        )


def _on_en_progreso(ticket: Ticket, *, actor=None):
    if ticket.inquilino:
        _create_for_users(
            [ticket.inquilino],
            ticket=ticket,
            mensaje='Trabajo en progreso',
            descripcion='El técnico ya está trabajando en tu solicitud.',
            tipo_alerta=TipoAlerta.INFO,
        )


def _on_resuelto(ticket: Ticket, *, actor=None):
    destinatarios = []
    if ticket.inquilino:
        destinatarios.append(ticket.inquilino)
    destinatarios.extend(list(_get_admins()))

    seen = set()
    unicos = []
    for d in destinatarios:
        if d.pk not in seen and (actor is None or d.pk != actor.pk):
            seen.add(d.pk)
            unicos.append(d)

    if unicos:
        _create_for_users(
            unicos,
            ticket=ticket,
            mensaje='Ticket resuelto',
            descripcion=f'El trabajo ha sido completado por {ticket.tecnico.get_full_name() if ticket.tecnico else "el técnico"}.',
            tipo_alerta=TipoAlerta.SUCCESS,
        )


def _on_cancelado(ticket: Ticket, *, actor=None):
    destinatarios = []
    if ticket.inquilino:
        destinatarios.append(ticket.inquilino)
    if ticket.tecnico:
        destinatarios.append(ticket.tecnico)

    seen = set()
    unicos = []
    for d in destinatarios:
        if d.pk not in seen and (actor is None or d.pk != actor.pk):
            seen.add(d.pk)
            unicos.append(d)

    if unicos:
        _create_for_users(
            unicos,
            ticket=ticket,
            mensaje='Ticket cancelado',
            descripcion='Este ticket ha sido cancelado.',
            tipo_alerta=TipoAlerta.ERROR,
        )
