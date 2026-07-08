"""Servicio de asignación de tickets a técnicos.

Centraliza la lógica de pesos por prioridad, cálculo de carga de trabajo
y selección del mejor técnico disponible.  Usado por:

* :func:`apps.ai_agent.tasks._run_ticket_analysis` — pre-asignación IA.
* :class:`apps.tickets.views.TicketValidateView` — validación admin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Case, F, IntegerField, Q, Sum, Value, When

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.accounts.models import CustomUser

# ── Pesos por prioridad ─────────────────────────────────────────────────
PRIORITY_WEIGHTS: dict[str, int] = {
    'ALTA': 3,
    'MEDIA': 2,
    'BAJA': 1,
}

# Estados que cuentan como "carga activa" del técnico
_ESTADOS_ACTIVOS = ('ASIGNADO', 'EN_CAMINO', 'EN_PROGRESO')


def get_priority_weight(prioridad: str) -> int:
    """Devuelve el peso numérico de una prioridad."""
    return PRIORITY_WEIGHTS.get(prioridad, 1)


def get_technician_workload(tecnico: CustomUser) -> int:
    """Calcula la carga de trabajo actual de un técnico (suma de pesos)."""
    return tecnico.carga_trabajo_actual


def can_assign_to(tecnico: CustomUser, prioridad: str) -> bool:
    """Verifica si un técnico puede recibir un ticket de la prioridad dada."""
    return tecnico.puede_aceptar_ticket(prioridad)


def get_available_technicians(prioridad: str) -> QuerySet:
    """Retorna técnicos activos con capacidad para la prioridad indicada.

    Ordenados por menor carga de trabajo (los más libres primero).
    """
    from apps.accounts.models import CustomUser

    peso = get_priority_weight(prioridad)

    # Anotar carga actual a cada técnico
    carga_annotation = Sum(
        Case(
            When(tickets_asignados__prioridad='ALTA', then=Value(3)),
            When(tickets_asignados__prioridad='MEDIA', then=Value(2)),
            When(tickets_asignados__prioridad='BAJA', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        filter=Q(tickets_asignados__estado__in=_ESTADOS_ACTIVOS),
        default=Value(0),
    )

    return (
        CustomUser.objects.filter(
            role=CustomUser.Roles.TECNICO,
            is_active=True,
        )
        .annotate(carga_actual=carga_annotation)
        .filter(carga_actual__lte=F('max_carga_trabajo') - peso)
        .order_by('carga_actual')
    )


def suggest_best_technician(
    categoria: str,
    prioridad: str,
) -> CustomUser | None:
    """Sugiere el mejor técnico considerando especialidad y carga disponible.

    Prioriza:
    1. Técnicos con la especialidad M2M que coincide con la categoría.
    2. Fallback: técnicos con el campo legacy `especialidad`.
    3. Entre ellos, el de menor carga de trabajo.
    4. Si ningún especialista está disponible, cualquier técnico disponible.

    Returns:
        Instancia de CustomUser o None si todos están al límite.
    """
    from django.db.models import Q

    disponibles = get_available_technicians(prioridad)

    # Preferir técnicos con especialidad M2M que coincida
    especialistas = disponibles.filter(
        Q(especialidades_tecnico__especialidad=categoria)
        | Q(especialidad=categoria)
    ).distinct()
    if especialistas.exists():
        return especialistas.first()

    # Fallback: cualquier técnico con capacidad
    return disponibles.first()


def get_technicians_with_workload() -> list[dict]:
    """Retorna todos los técnicos activos con su carga de trabajo anotada.

    Útil para mostrar al admin la lista de técnicos con su estado de carga.
    """
    from apps.accounts.models import CustomUser

    carga_annotation = Sum(
        Case(
            When(tickets_asignados__prioridad='ALTA', then=Value(3)),
            When(tickets_asignados__prioridad='MEDIA', then=Value(2)),
            When(tickets_asignados__prioridad='BAJA', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
        filter=Q(tickets_asignados__estado__in=_ESTADOS_ACTIVOS),
        default=Value(0),
    )

    tecnicos = (
        CustomUser.objects.filter(
            role=CustomUser.Roles.TECNICO,
            is_active=True,
        )
        .annotate(carga_actual=carga_annotation)
        .order_by('carga_actual', 'first_name')
    )

    return [
        {
            'id': t.id,
            'nombre': t.get_full_name(),
            'especialidad': t.especialidad,
            'carga_actual': t.carga_actual,
            'max_carga': t.max_carga_trabajo,
            'carga_disponible': max(0, t.max_carga_trabajo - t.carga_actual),
        }
        for t in tecnicos
    ]
