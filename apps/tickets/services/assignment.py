
from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Case, F, IntegerField, Q, Sum, Value, When

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.accounts.models import CustomUser

PRIORITY_WEIGHTS: dict[str, int] = {
    'ALTA': 3,
    'MEDIA': 2,
    'BAJA': 1,
}

_ESTADOS_ACTIVOS = ('ASIGNADO', 'EN_CAMINO', 'EN_PROGRESO')


def get_priority_weight(prioridad: str) -> int:
    return PRIORITY_WEIGHTS.get(prioridad, 1)


def get_technician_workload(tecnico: CustomUser) -> int:
    return tecnico.carga_trabajo_actual


def can_assign_to(tecnico: CustomUser, prioridad: str) -> bool:
    return tecnico.puede_aceptar_ticket(prioridad)


def get_available_technicians(prioridad: str) -> QuerySet:
    from apps.accounts.models import CustomUser

    peso = get_priority_weight(prioridad)

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
    from django.db.models import Q

    disponibles = get_available_technicians(prioridad)

    especialistas = disponibles.filter(
        Q(especialidades_tecnico__especialidad=categoria)
        | Q(especialidad=categoria)
    ).distinct()
    if especialistas.exists():
        return especialistas.first()

    return disponibles.first()


def get_technicians_with_workload() -> list[dict]:
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
