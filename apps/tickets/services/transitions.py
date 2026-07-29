
from __future__ import annotations

from typing import Iterable, Mapping, Set

from django.db import transaction
from django.utils import timezone

from apps.tickets.models import HistorialEstado, Ticket, TicketStatus

_TRANSITIONS: Mapping[str, Set[str]] = {
    TicketStatus.CREADO_PENDIENTE_IA: {
        TicketStatus.ANALIZADO_POR_IA,
        TicketStatus.PENDIENTE_VALIDACION,
        TicketStatus.CANCELADO,
    },
    TicketStatus.ANALIZADO_POR_IA: {
        TicketStatus.PENDIENTE_VALIDACION,
        TicketStatus.CANCELADO,
    },
    TicketStatus.PENDIENTE_VALIDACION: {
        TicketStatus.APROBADO,
        TicketStatus.CANCELADO,
    },
    TicketStatus.APROBADO: {
        TicketStatus.ASIGNADO,
        TicketStatus.CANCELADO,
    },
    TicketStatus.ASIGNADO: {
        TicketStatus.EN_CAMINO,
        TicketStatus.CANCELADO,
    },
    TicketStatus.EN_CAMINO: {
        TicketStatus.EN_PROGRESO,
        TicketStatus.CANCELADO,
    },
    TicketStatus.EN_PROGRESO: {
        TicketStatus.RESUELTO,
        TicketStatus.CANCELADO,
    },
    TicketStatus.RESUELTO: set(),
    TicketStatus.CANCELADO: set(),
}

_ROLE_RULES: Mapping[tuple[str, str], Set[str]] = {
    (TicketStatus.CREADO_PENDIENTE_IA, TicketStatus.ANALIZADO_POR_IA): {'SYSTEM'},
    (TicketStatus.CREADO_PENDIENTE_IA, TicketStatus.PENDIENTE_VALIDACION): {'SYSTEM', 'ADMIN'},
    (TicketStatus.ANALIZADO_POR_IA, TicketStatus.PENDIENTE_VALIDACION): {'SYSTEM', 'ADMIN'},
    (TicketStatus.PENDIENTE_VALIDACION, TicketStatus.APROBADO): {'ADMIN'},
    (TicketStatus.APROBADO, TicketStatus.ASIGNADO): {'INQUILINO'},
    (TicketStatus.ASIGNADO, TicketStatus.EN_CAMINO): {'TECNICO'},
    (TicketStatus.EN_CAMINO, TicketStatus.EN_PROGRESO): {'TECNICO'},
    (TicketStatus.EN_PROGRESO, TicketStatus.RESUELTO): {'TECNICO'},
}
_ESTADOS_CANCELABLES_POR_INQUILINO: Set[str] = {
    TicketStatus.CREADO_PENDIENTE_IA,
    TicketStatus.ANALIZADO_POR_IA,
    TicketStatus.PENDIENTE_VALIDACION,
    TicketStatus.APROBADO,
    TicketStatus.ASIGNADO,
}


class InvalidTransitionError(Exception):
    pass


class TransitionPermissionError(Exception):
    pass


def allowed_transitions_for(ticket: Ticket, *, role: str | None = None) -> Iterable[str]:
    destinos = _TRANSITIONS.get(ticket.estado, set())
    if role is None:
        return destinos
    permitidos = []
    for destino in destinos:
        roles_ok = _role_allowed_for(ticket.estado, destino)
        if role in roles_ok or (role == 'SYSTEM' and 'SYSTEM' in roles_ok):
            permitidos.append(destino)
    return permitidos


def _role_allowed_for(origen: str, destino: str) -> Set[str]:
    if destino == TicketStatus.CANCELADO:
        roles = {'ADMIN', 'SYSTEM'}
        if origen in _ESTADOS_CANCELABLES_POR_INQUILINO:
            roles = roles | {'INQUILINO'}
        return roles
    return _ROLE_RULES.get((origen, destino), set())


class WorkloadExceededError(Exception):
    pass


@transaction.atomic
def transition_ticket(
    ticket: Ticket,
    *,
    nuevo_estado: str,
    actor=None,
    actor_role: str | None = None,
    nota: str = '',
) -> Ticket:
    estado_actual = ticket.estado
    if nuevo_estado not in _TRANSITIONS.get(estado_actual, set()):
        raise InvalidTransitionError(
            f'No se permite pasar de {estado_actual} a {nuevo_estado}.'
        )

    if actor_role is None and actor is not None:
        actor_role = getattr(actor, 'role', None) or ('ADMIN' if getattr(actor, 'is_superuser', False) else None)

    permitidos = _role_allowed_for(estado_actual, nuevo_estado)
    if actor_role not in permitidos:
        raise TransitionPermissionError(
            f'El rol {actor_role} no puede ejecutar la transición {estado_actual} → {nuevo_estado}.'
        )

    if nuevo_estado == TicketStatus.ASIGNADO:
        if not ticket.tecnico:
            raise InvalidTransitionError(
                'No se puede asignar un ticket sin técnico.'
            )
        if not ticket.tecnico.puede_aceptar_ticket(ticket.prioridad):
            raise WorkloadExceededError(
                f'{ticket.tecnico.get_full_name()} ha alcanzado su límite de '
                f'carga de trabajo ({ticket.tecnico.carga_trabajo_actual}/'
                f'{ticket.tecnico.max_carga_trabajo} puntos). '
                f'Selecciona otro técnico o ajusta su límite.'
            )

    ticket.estado = nuevo_estado
    update_fields = ['estado', 'actualizado_en']
    if nuevo_estado == TicketStatus.RESUELTO and ticket.resuelto_en is None:
        ticket.resuelto_en = timezone.now()
        update_fields.append('resuelto_en')
    ticket.save(update_fields=update_fields)

    HistorialEstado.objects.create(
        ticket=ticket,
        estado_anterior=estado_actual,
        estado_nuevo=nuevo_estado,
        actor=actor if actor and actor.is_authenticated else None,
        nota=nota,
    )

    from apps.tickets.services.notify import notify_transition
    notify_transition(
        ticket,
        estado_anterior=estado_actual,
        nuevo_estado=nuevo_estado,
        actor=actor,
    )

    return ticket
