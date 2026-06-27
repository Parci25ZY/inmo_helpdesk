"""Máquina de estados de tickets.

Centraliza las reglas de transición y las verificaciones de rol.
Las vistas y las tasks asíncronas (IA) deben usar exclusivamente
:func:`transition_ticket` para mover un ticket de un estado a otro.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Set

from django.db import transaction
from django.utils import timezone

from apps.tickets.models import HistorialEstado, Ticket, TicketStatus

# ── Mapa de transiciones permitidas ─────────────────────────────────────
_TRANSITIONS: Mapping[str, Set[str]] = {
    TicketStatus.CREADO_PENDIENTE_IA: {
        TicketStatus.ANALIZADO_POR_IA,
        TicketStatus.PENDIENTE_VALIDACION,  # fallback si la IA falla
        TicketStatus.CANCELADO,
    },
    TicketStatus.ANALIZADO_POR_IA: {
        TicketStatus.PENDIENTE_VALIDACION,
        TicketStatus.ASIGNADO,  # auto-asignación IA con alta confianza
        TicketStatus.CANCELADO,
    },
    TicketStatus.PENDIENTE_VALIDACION: {
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

# ── Roles autorizados por transición ────────────────────────────────────
# Clave: (origen, destino) → conjunto de roles permitidos.
_ROLE_RULES: Mapping[tuple[str, str], Set[str]] = {
    (TicketStatus.CREADO_PENDIENTE_IA, TicketStatus.ANALIZADO_POR_IA): {'SYSTEM'},
    (TicketStatus.CREADO_PENDIENTE_IA, TicketStatus.PENDIENTE_VALIDACION): {'SYSTEM', 'ADMIN'},
    (TicketStatus.ANALIZADO_POR_IA, TicketStatus.PENDIENTE_VALIDACION): {'SYSTEM', 'ADMIN'},
    (TicketStatus.ANALIZADO_POR_IA, TicketStatus.ASIGNADO): {'SYSTEM', 'ADMIN'},
    (TicketStatus.PENDIENTE_VALIDACION, TicketStatus.ASIGNADO): {'ADMIN'},
    (TicketStatus.ASIGNADO, TicketStatus.EN_CAMINO): {'TECNICO', 'ADMIN'},
    (TicketStatus.EN_CAMINO, TicketStatus.EN_PROGRESO): {'TECNICO', 'ADMIN'},
    (TicketStatus.EN_PROGRESO, TicketStatus.RESUELTO): {'TECNICO', 'ADMIN'},
}
# La cancelación está permitida desde cualquier no-terminal para ADMIN.


class InvalidTransitionError(Exception):
    """Se intenta una transición que no existe en la máquina."""


class TransitionPermissionError(Exception):
    """El actor no tiene permisos para esa transición."""


def allowed_transitions_for(ticket: Ticket, *, role: str | None = None) -> Iterable[str]:
    """Devuelve la lista de estados destino válidos para el ticket actual.

    Si se pasa ``role`` filtra adicionalmente por las reglas de rol.
    """
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
    """Conjunto de roles permitidos para una transición específica."""
    if destino == TicketStatus.CANCELADO:
        return {'ADMIN', 'SYSTEM'}
    return _ROLE_RULES.get((origen, destino), set())


@transaction.atomic
def transition_ticket(
    ticket: Ticket,
    *,
    nuevo_estado: str,
    actor=None,
    actor_role: str | None = None,
    nota: str = '',
) -> Ticket:
    """Mueve un ticket a un nuevo estado de forma transaccional.

    Args:
        ticket: instancia a mutar.
        nuevo_estado: valor de :class:`TicketStatus`.
        actor: usuario que ejecuta la acción (None para tareas del sistema).
        actor_role: 'ADMIN' | 'TECNICO' | 'INQUILINO' | 'SYSTEM'.
            Si es None se infiere desde ``actor.role``.
        nota: comentario opcional añadido al historial.

    Raises:
        InvalidTransitionError: si la transición no existe.
        TransitionPermissionError: si el rol no puede ejecutarla.
    """
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
    return ticket
