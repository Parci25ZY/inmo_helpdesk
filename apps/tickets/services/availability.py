"""Servicio de disponibilidad horaria de técnicos — bloques discretos de 1h.

Calcula bloques libres/ocupados/buffer considerando:
- Horario de trabajo semanal (HorarioTrabajo)
- Tickets ya programados para esas franjas
- Duración estimada según prioridad (BAJA=1h, MEDIA=2h, ALTA=3h)
- Buffer de traslado de 30 min entre trabajos (Opción A: bloque completo)

Usado por:
* Vista de detalle del ticket — panel de auto-agenda del inquilino.
* API AJAX — actualización dinámica al seleccionar técnico.
* Servicio de asignación — auto-sugerencia de horario.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import CustomUser

# ── Constantes ──────────────────────────────────────────────────────────

# Duración de visita según prioridad (en horas = cantidad de bloques)
VISIT_DURATION: dict[str, int] = {
    'BAJA': 1,
    'MEDIA': 2,
    'ALTA': 3,
}

# Buffer de traslado entre trabajos (minutos)
TRAVEL_BUFFER_MINUTES: int = 30

DIAS_LABELS = {
    0: 'Lunes', 1: 'Martes', 2: 'Miércoles',
    3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo',
}

DIAS_LABELS_SHORT = {
    0: 'Lun', 1: 'Mar', 2: 'Mié',
    3: 'Jue', 4: 'Vie', 5: 'Sáb', 6: 'Dom',
}

# ── Estados de un bloque horario ────────────────────────────────────────

BLOCK_LIBRE = 'libre'
BLOCK_OCUPADO = 'ocupado'
BLOCK_BUFFER = 'buffer'
BLOCK_PASADO = 'pasado'


def get_visit_duration(prioridad: str) -> int:
    """Retorna la duración estimada de visita en horas según prioridad."""
    return VISIT_DURATION.get(prioridad, 2)


# ── Generación de bloques discretos de 1 hora ──────────────────────────


def _generate_hour_blocks(hora_inicio: time, hora_fin: time) -> list[dict]:
    """Genera bloques discretos de 1 hora entre hora_inicio y hora_fin.

    Cada bloque es un dict con:
    - hora_inicio: time (ej. 08:00)
    - hora_fin: time (ej. 09:00)
    - estado: 'libre' (default)
    - ticket_id: None
    - ticket_titulo: ''

    Solo genera bloques de hora completa.  Si la franja termina a las
    12:30, el último bloque completo es 11:00–12:00 (12:00–12:30 se
    descarta porque no cabe una hora entera).
    """
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
    """Retorna todos los bloques de 1h para un técnico en una fecha.

    Combina todos los turnos del día (ej. 08:00–12:00 y 14:00–18:00)
    y genera bloques discretos de 1 hora.

    Returns:
        Lista de dicts con keys: hora_inicio, hora_fin, estado,
        ticket_id, ticket_titulo.
    """
    from apps.tickets.models import Ticket

    # 1. Generar bloques base desde el horario del técnico
    horarios = tecnico.get_horario_fecha(fecha)
    bloques: list[dict] = []
    for h in horarios:
        bloques.extend(_generate_hour_blocks(h.hora_inicio, h.hora_fin))

    if not bloques:
        return []

    # 2. Obtener tickets programados para ese día
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

    # 3. Marcar bloques ocupados y con buffer
    base_date = date.today()
    buffer_delta = timedelta(minutes=TRAVEL_BUFFER_MINUTES)

    for bloque in bloques:
        bloque_inicio = datetime.combine(base_date, bloque['hora_inicio'])
        bloque_fin = datetime.combine(base_date, bloque['hora_fin'])

        for ticket in tickets_dia:
            t_inicio = datetime.combine(base_date, ticket['hora_programada_inicio'])
            t_fin = datetime.combine(base_date, ticket['hora_programada_fin'])

            # ¿El bloque se solapa con el ticket?
            if bloque_inicio < t_fin and bloque_fin > t_inicio:
                bloque['estado'] = BLOCK_OCUPADO
                bloque['ticket_id'] = ticket['id']
                bloque['ticket_titulo'] = ticket['titulo']
                break  # Un bloque solo puede estar ocupado por un ticket

            # ¿El bloque cae dentro del buffer de traslado post-ticket?
            # Buffer: desde t_fin hasta t_fin + TRAVEL_BUFFER_MINUTES
            # Opción A: si cualquier parte del bloque toca el buffer,
            # el bloque completo se marca como no disponible.
            buffer_inicio = t_fin
            buffer_fin = t_fin + buffer_delta

            if bloque_inicio < buffer_fin and bloque_fin > buffer_inicio:
                # Solo marcar como buffer si no está ya ocupado
                if bloque['estado'] == BLOCK_LIBRE:
                    bloque['estado'] = BLOCK_BUFFER
                    bloque['ticket_id'] = ticket['id']
                    bloque['ticket_titulo'] = f'Traslado ({ticket["titulo"]})'
                break

    return bloques


# ── Funciones públicas de alto nivel ────────────────────────────────────


def get_technician_day_schedule(tecnico: 'CustomUser', fecha: date) -> list[dict]:
    """Retorna los bloques de 1h de un técnico para una fecha.

    Wrapper de compatibilidad que retorna la misma estructura que
    ``get_hour_blocks_for_day`` pero con el campo legacy ``ocupado``
    para mantener compatibilidad con templates/APIs existentes.

    Si la fecha es hoy, los bloques cuya hora_fin ya pasó se marcan
    como ``pasado`` para que no se muestren como disponibles.

    Cada bloque incluye:
    - hora_inicio, hora_fin: time objects
    - ocupado: bool (True si estado != 'libre')
    - estado: 'libre' | 'ocupado' | 'buffer' | 'pasado'
    - ticket_id: int | None
    - ticket_titulo: str
    """
    bloques = get_hour_blocks_for_day(tecnico, fecha)

    # Marcar bloques que ya pasaron si la fecha es hoy
    hoy = timezone.localdate()
    if fecha == hoy:
        ahora = timezone.localtime(timezone.now()).time()
        for bloque in bloques:
            # Si la hora de fin del bloque ya pasó, no es agendable
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
    """Retorna la disponibilidad de un técnico para múltiples días.

    Returns:
        Lista de dicts con keys:
        - fecha: date
        - dia_label: str (ej. 'Lunes')
        - dia_label_short: str (ej. 'Lun')
        - bloques: list[dict] resultado de get_technician_day_schedule
        - tiene_horario: bool
    """
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
    """Panel de disponibilidad de todos los técnicos para un día.

    Filtra opcionalmente por especialidad (categoría del ticket).

    Returns:
        Lista de dicts con keys:
        - tecnico: CustomUser instance
        - nombre: str
        - especialidades: str
        - bloques: list[dict]
        - tiene_horario: bool
        - disponible_ahora: bool
        - carga_actual: int
        - max_carga: int
    """
    from apps.accounts.models import CustomUser

    tecnicos = CustomUser.objects.filter(
        role=CustomUser.Roles.TECNICO,
        is_active=True,
    ).prefetch_related('especialidades_tecnico', 'horarios').order_by('first_name')

    if categoria:
        # Filtrar por técnicos que tengan la especialidad
        tecnicos_con_esp = tecnicos.filter(
            Q(especialidades_tecnico__especialidad=categoria)
            | Q(especialidad=categoria)
        ).distinct()
        # Incluir también los demás técnicos al final
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
    """Encuentra todos los grupos de N bloques consecutivos libres.

    Args:
        bloques: lista de bloques de 1h ya marcados con estado.
        cantidad: número de bloques consecutivos requeridos.

    Returns:
        Lista de grupos, cada grupo es una lista de N bloques consecutivos.
    """
    grupos: list[list[dict]] = []
    buffer: list[dict] = []

    for bloque in bloques:
        if bloque['estado'] == BLOCK_LIBRE:
            buffer.append(bloque)
            if len(buffer) >= cantidad:
                # Tomar los últimos N bloques
                grupos.append(list(buffer[-cantidad:]))
        else:
            buffer = []

    return grupos


def auto_suggest_schedule(
    tecnico: 'CustomUser',
    prioridad: str,
    desde: date | None = None,
) -> dict | None:
    """Sugiere automáticamente una fecha y hora para un ticket.

    Busca el primer grupo de N bloques consecutivos libres donde
    N = duración según prioridad del ticket.

    Returns:
        dict con 'fecha', 'hora_inicio', 'hora_fin', 'duracion_horas'
        o None si no hay disponibilidad en los próximos 14 días.
    """
    duracion_bloques = get_visit_duration(prioridad)

    if desde is None:
        desde = timezone.localdate()

    for offset in range(14):  # Buscar en los próximos 14 días
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
