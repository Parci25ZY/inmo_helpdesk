
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import CustomUser


VISIT_DURATION: dict[str, int] = {
    'BAJA': 1,
    'MEDIA': 2,
    'ALTA': 3,
}

TRAVEL_BUFFER_MINUTES: int = 30

DIAS_LABELS = {
    0: 'Lunes', 1: 'Martes', 2: 'Miércoles',
    3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo',
}

DIAS_LABELS_SHORT = {
    0: 'Lun', 1: 'Mar', 2: 'Mié',
    3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom',
}


BLOCK_LIBRE = 'libre'
BLOCK_OCUPADO = 'ocupado'
BLOCK_BUFFER = 'buffer'
BLOCK_PASADO = 'pasado'


def get_visit_duration(prioridad: str) -> int:
    return VISIT_DURATION.get(prioridad, 2)




def _generate_hour_blocks(hora_inicio: time, hora_fin: time) -> list[dict]:
    base_date = date.today()
    cursor = datetime.combine(base_date, hora_inicio)
    fin_dt = datetime.combine(base_date, hora_fin)
    bloques: list[dict] = []

    while cursor + timedelta(hours=1) <= fin_dt:
        bloques.append({
            'hora_inicio': cursor.time(),
            'hora_fin': (cursor + timedelta(hours=1)).time(),
            'estado': BLOCK_LIBRE,
            'ticket_id': None,
            'ticket_titulo': '',
        })
        cursor += timedelta(hours=1)

    return bloques


def get_hour_blocks_for_day(
    tecnico: 'CustomUser',
    fecha: date,
) -> list[dict]:
    from apps.tickets.models import Ticket

    horarios = tecnico.get_horario_fecha(fecha)
    bloques: list[dict] = []
    for h in horarios:
        bloques.extend(_generate_hour_blocks(h.hora_inicio, h.hora_fin))

    if not bloques:
        return []

    tickets_dia = list(
        Ticket.objects.filter(
            tecnico=tecnico,
            fecha_programada=fecha,
            estado__in=('ASIGNADO', 'EN_CAMINO', 'EN_PROGRESO'),
        )
        .values('id', 'titulo', 'hora_programada_inicio', 'hora_programada_fin')
        .order_by('hora_programada_inicio')
    )

    if not tickets_dia:
        return bloques

    base_date = date.today()
    buffer_delta = timedelta(minutes=TRAVEL_BUFFER_MINUTES)

    for bloque in bloques:
        bloque_inicio = datetime.combine(base_date, bloque['hora_inicio'])
        bloque_fin = datetime.combine(base_date, bloque['hora_fin'])

        for ticket in tickets_dia:
            t_inicio = datetime.combine(base_date, ticket['hora_programada_inicio'])
            t_fin = datetime.combine(base_date, ticket['hora_programada_fin'])

            if bloque_inicio < t_fin and bloque_fin > t_inicio:
                bloque['estado'] = BLOCK_OCUPADO
                bloque['ticket_id'] = ticket['id']
                bloque['ticket_titulo'] = ticket['titulo']
                break

            buffer_inicio = t_fin
            buffer_fin = t_fin + buffer_delta

            if bloque_inicio < buffer_fin and bloque_fin > buffer_inicio:
                if bloque['estado'] == BLOCK_LIBRE:
                    bloque['estado'] = BLOCK_BUFFER
                    bloque['ticket_id'] = ticket['id']
                    bloque['ticket_titulo'] = f'Traslado ({ticket["titulo"]})'
                break

    return bloques




def get_technician_day_schedule(tecnico: 'CustomUser', fecha: date) -> list[dict]:
    bloques = get_hour_blocks_for_day(tecnico, fecha)

    hoy = timezone.localdate()
    if fecha == hoy:
        ahora = timezone.localtime(timezone.now()).time()
        for bloque in bloques:
            if bloque['hora_fin'] <= ahora and bloque['estado'] == BLOCK_LIBRE:
                bloque['estado'] = BLOCK_PASADO

    for bloque in bloques:
        bloque['ocupado'] = bloque['estado'] != BLOCK_LIBRE

    return bloques


def get_technician_availability_multi_day(
    tecnico: 'CustomUser',
    desde: date | None = None,
    dias: int = 4,
) -> list[dict]:
    if desde is None:
        desde = timezone.localdate()

    resultado = []
    for offset in range(dias):
        fecha = desde + timedelta(days=offset)
        bloques = get_technician_day_schedule(tecnico, fecha)
        resultado.append({
            'fecha': fecha,
            'dia_label': DIAS_LABELS.get(fecha.weekday(), ''),
            'dia_label_short': DIAS_LABELS_SHORT.get(fecha.weekday(), ''),
            'bloques': bloques,
            'tiene_horario': len(bloques) > 0,
        })

    return resultado


def get_all_technicians_availability(
    fecha: date,
    categoria: str | None = None,
    prioridad: str = 'MEDIA',
) -> list[dict]:
    from apps.accounts.models import CustomUser

    tecnicos = CustomUser.objects.filter(
        role=CustomUser.Roles.TECNICO,
        is_active=True,
    ).prefetch_related('especialidades_tecnico', 'horarios').order_by('first_name')

    if categoria:
        tecnicos_con_esp = tecnicos.filter(
            Q(especialidades_tecnico__especialidad=categoria)
            | Q(especialidad=categoria)
        ).distinct()
        tecnicos_sin_esp = tecnicos.exclude(
            pk__in=tecnicos_con_esp.values_list('pk', flat=True)
        )
        tecnicos_ordenados = list(tecnicos_con_esp) + list(tecnicos_sin_esp)
    else:
        tecnicos_ordenados = list(tecnicos)

    resultado = []
    for t in tecnicos_ordenados:
        bloques = get_technician_day_schedule(t, fecha)
        resultado.append({
            'tecnico': t,
            'nombre': t.get_full_name(),
            'especialidades': t.especialidades_display,
            'bloques': bloques,
            'tiene_horario': len(bloques) > 0,
            'disponible_ahora': t.esta_disponible_ahora(),
            'carga_actual': t.carga_trabajo_actual,
            'max_carga': t.max_carga_trabajo,
            'tiene_especialidad': (
                t.tiene_especialidad(categoria) if categoria else False
            ),
        })

    return resultado


def find_consecutive_free_blocks(
    bloques: list[dict],
    cantidad: int,
) -> list[list[dict]]:
    grupos: list[list[dict]] = []
    buffer: list[dict] = []

    for bloque in bloques:
        if bloque['estado'] == BLOCK_LIBRE:
            buffer.append(bloque)
            if len(buffer) >= cantidad:
                grupos.append(list(buffer[-cantidad:]))
        else:
            buffer = []

    return grupos


def auto_suggest_schedule(
    tecnico: 'CustomUser',
    prioridad: str,
    desde: date | None = None,
) -> dict | None:
    duracion_bloques = get_visit_duration(prioridad)

    if desde is None:
        desde = timezone.localdate()

    for offset in range(14):
        fecha = desde + timedelta(days=offset)
        bloques = get_technician_day_schedule(tecnico, fecha)

        grupos = find_consecutive_free_blocks(bloques, duracion_bloques)

        if grupos:
            primer_grupo = grupos[0]
            return {
                'fecha': fecha,
                'hora_inicio': primer_grupo[0]['hora_inicio'],
                'hora_fin': primer_grupo[-1]['hora_fin'],
                'duracion_horas': duracion_bloques,
            }

    return None
