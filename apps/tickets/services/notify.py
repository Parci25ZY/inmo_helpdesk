"""Servicio de creación automática de notificaciones in-app.

Se invoca desde ``transition_ticket()`` tras cada cambio de estado
para alertar a los usuarios relevantes según la transición.

Mapa de notificaciones:
───────────────────────────────────────────────────────────────────
Transición                  │ Destinatario  │ Tipo    │ Mensaje
────────────────────────────┼───────────────┼─────────┼────────────
→ PENDIENTE_VALIDACION      │ Admin(s)      │ WARNING │ Requiere validación
                            │               │         │ (+ correo HTML y correo
                            │               │         │ de texto de "nuevo ticket")
→ APROBADO                  │ Inquilino     │ SUCCESS │ Aprobado, agenda tu visita
→ ASIGNADO                  │ Técnico       │ INFO    │ Auto-asignado / agendado
→ EN_CAMINO                 │ Inquilino     │ INFO    │ Técnico en camino
→ EN_PROGRESO               │ Inquilino     │ INFO    │ Trabajo en progreso
→ RESUELTO                  │ Inquilino+Adm │ SUCCESS │ Ticket resuelto
→ CANCELADO                 │ Inquilino     │ ERROR   │ Ticket cancelado
Nuevo mensaje               │ Contrapartida │ INFO    │ Nuevo mensaje

Nota: las notificaciones de "nuevo ticket" (in-app + los dos correos) se
disparan aquí, en PENDIENTE_VALIDACION, y no en el momento de creación del
ticket — para entonces la IA (o su fallback) ya fijó categoria/prioridad
reales. Antes se enviaban al crear el ticket y mostraban siempre los
valores por defecto del modelo (OTRO/MEDIA) en vez de la clasificación
real.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.accounts.models import CustomUser

from apps.tickets.models import Notificacion, Ticket, TicketStatus, TipoAlerta

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_admins():
    """Retorna queryset de todos los administradores activos."""
    return CustomUser.objects.filter(
        role=CustomUser.Roles.ADMIN,
        is_active=True,
    )


def _create_for_users(users, *, ticket, mensaje, descripcion='', tipo_alerta=TipoAlerta.INFO):
    """Crea notificaciones en bulk para una lista de usuarios."""
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


# ── Disparadores principales ────────────────────────────────────────────


def notify_ticket_created(ticket: Ticket):
    """Nuevo ticket creado por inquilino → notificar a Admin(s)."""
    admins = _get_admins()
    _create_for_users(
        admins,
        ticket=ticket,
        mensaje=f'Nuevo ticket — {ticket.get_prioridad_display()}',
        descripcion=ticket.descripcion[:200] if ticket.descripcion else '',
        tipo_alerta=TipoAlerta.WARNING,
    )


def notify_transition(ticket: Ticket, *, estado_anterior: str, nuevo_estado: str, actor=None):
    """Genera notificaciones automáticas según la transición de estado.

    Se invoca desde ``transition_ticket()`` después de guardar.
    """
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
    """Nuevo mensaje en chat → notificar a la contraparte."""
    destinatarios = []

    if hasattr(autor, 'role'):
        if autor.role == CustomUser.Roles.INQUILINO:
            # Inquilino escribe → notificar a técnico y admin(s)
            if ticket.tecnico:
                destinatarios.append(ticket.tecnico)
            destinatarios.extend(list(_get_admins()))
        elif autor.role == CustomUser.Roles.TECNICO:
            # Técnico escribe → notificar a inquilino y admin(s)
            if ticket.inquilino:
                destinatarios.append(ticket.inquilino)
            destinatarios.extend(list(_get_admins()))
        else:
            # Admin escribe → notificar a inquilino y técnico
            if ticket.inquilino:
                destinatarios.append(ticket.inquilino)
            if ticket.tecnico:
                destinatarios.append(ticket.tecnico)

    # Eliminar duplicados y excluir al autor
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


# ── Handlers por estado ────────────────────────────────────────────────


def _on_pendiente_validacion(ticket: Ticket, *, actor=None):
    """→ PENDIENTE_VALIDACION: notificar admin(s) que requiere validación.

    Este es también el punto donde se avisa por primera vez a los admins que
    existe un ticket nuevo (in-app + los dos correos) — se hace aquí y no al
    crear el ticket porque recién en este punto `ticket.categoria` y
    `ticket.prioridad` reflejan la clasificación real de la IA (o el
    resultado de su fallback), no los valores por defecto del modelo.
    """
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
    """→ APROBADO: notificar inquilino que puede agendar."""
    if ticket.inquilino:
        _create_for_users(
            [ticket.inquilino],
            ticket=ticket,
            mensaje='Aprobado — Agenda tu visita',
            descripcion='Tu reporte fue validado. Selecciona un horario para la visita del técnico.',
            tipo_alerta=TipoAlerta.SUCCESS,
        )


def _on_asignado(ticket: Ticket, *, actor=None):
    """→ ASIGNADO: notificar técnico que tiene un nuevo trabajo."""
    destinatarios = []

    if ticket.tecnico:
        destinatarios.append(ticket.tecnico)

    # También notificar al admin si el inquilino agendó
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
    """→ EN_CAMINO: notificar inquilino que el técnico salió."""
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
    """→ EN_PROGRESO: notificar inquilino que el trabajo empezó."""
    if ticket.inquilino:
        _create_for_users(
            [ticket.inquilino],
            ticket=ticket,
            mensaje='Trabajo en progreso',
            descripcion='El técnico ya está trabajando en tu solicitud.',
            tipo_alerta=TipoAlerta.INFO,
        )


def _on_resuelto(ticket: Ticket, *, actor=None):
    """→ RESUELTO: notificar inquilino y admin(s)."""
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
    """→ CANCELADO: notificar inquilino y técnico."""
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
