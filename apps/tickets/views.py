"""Vistas del módulo Tickets.

Implementan el ciclo de vida completo:
  * Listado filtrado por rol.
  * Detalle con timeline de historial y galería de evidencias.
  * Creación por el inquilino.
  * Validación administrativa (transición a ASIGNADO).
  * Transiciones operativas del técnico.
  * Subida de evidencias.

Todas las transiciones de estado pasan por
:func:`apps.tickets.services.transitions.transition_ticket`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    View,
)

from apps.accounts.models import CustomUser

from .forms import (
    InquilinoScheduleForm,
    MensajeForm,
    TicketAdminValidateForm,
    TicketCreateForm,
    TicketResolutionForm,
    TicketTransitionForm,
)
from .models import EvidenciaTicket, MensajeTicket, Ticket, TicketPriority, TicketStatus
from .services.transitions import (
    InvalidTransitionError,
    TransitionPermissionError,
    WorkloadExceededError,
    allowed_transitions_for,
    transition_ticket,
)
from .services.assignment import can_assign_to, get_priority_weight
from .services.availability import (
    BLOCK_LIBRE,
    auto_suggest_schedule,
    find_consecutive_free_blocks,
    get_technician_availability_multi_day,
    get_visit_duration,
)


# Labels legibles para cada transición — reemplaza el enum crudo en la UI
_TRANSITION_LABELS: dict[str, str] = {
    TicketStatus.ANALIZADO_POR_IA: 'Marcar como analizado',
    TicketStatus.PENDIENTE_VALIDACION: 'Enviar a validación',
    TicketStatus.APROBADO: 'Aprobar ticket',
    TicketStatus.ASIGNADO: 'Confirmar asignación',
    TicketStatus.EN_CAMINO: 'Salir hacia el sitio',
    TicketStatus.EN_PROGRESO: 'Iniciar intervención',
    TicketStatus.RESUELTO: 'Marcar como resuelto',
    TicketStatus.CANCELADO: 'Cancelar ticket',
}


# ── Mixins ──────────────────────────────────────────────────────────────

class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe acceso a vistas a un conjunto de roles.

    Definir ``allowed_roles`` como tupla de strings (ADMIN/TECNICO/INQUILINO).
    Los superusuarios siempre pasan.
    """

    allowed_roles: tuple[str, ...] = ()

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.role in self.allowed_roles

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('login')
        messages.error(self.request, 'No tienes permisos para esa acción.')
        return redirect('dashboard')


# ── Listado ─────────────────────────────────────────────────────────────

class TicketListView(LoginRequiredMixin, ListView):
    """Listado de tickets filtrado según rol del usuario."""

    model = Ticket
    template_name = 'tickets/list.html'
    context_object_name = 'tickets'
    paginate_by = 12

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad', 'unidad__edificio',
        )
        if user.is_admin:
            pass  # Admin ve todo
        elif user.is_tecnico:
            qs = qs.filter(tecnico=user)
        else:  # Inquilino
            qs = qs.filter(inquilino=user)

        estado = self.request.GET.get('estado', '').strip()
        prioridad = self.request.GET.get('prioridad', '').strip()
        search = self.request.GET.get('search', '').strip()

        if estado:
            qs = qs.filter(estado=estado)
        if prioridad:
            qs = qs.filter(prioridad=prioridad)
        if search:
            qs = qs.filter(
                Q(titulo__icontains=search)
                | Q(descripcion__icontains=search)
                | Q(unidad__numero__icontains=search)
                | Q(unidad__edificio__nombre__icontains=search)
            )
        prioridad_orden = Case(
            When(prioridad=TicketPriority.ALTA, then=Value(1)),
            When(prioridad=TicketPriority.MEDIA, then=Value(2)),
            When(prioridad=TicketPriority.BAJA, then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
        return qs.annotate(prioridad_orden=prioridad_orden).order_by('prioridad_orden', '-creado_en')

    def _base_scope(self):
        """Queryset base filtrado por rol para KPIs (sin filtros de búsqueda)."""
        user = self.request.user
        qs = Ticket.objects.all()
        if user.is_tecnico:
            qs = qs.filter(tecnico=user)
        elif not user.is_admin:
            qs = qs.filter(inquilino=user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        base_qs = self._base_scope()

        # Una sola query con aggregate en vez de 4 count() separadas
        _estados_pendientes = (
            [TicketStatus.ASIGNADO] if user.is_tecnico else
            [TicketStatus.CREADO_PENDIENTE_IA, TicketStatus.ANALIZADO_POR_IA,
             TicketStatus.PENDIENTE_VALIDACION]
        )
        stats = base_qs.aggregate(
            kpi_pendientes=Count('pk', filter=Q(estado__in=_estados_pendientes)),
            kpi_en_proceso=Count('pk', filter=Q(estado__in=[
                TicketStatus.ASIGNADO, TicketStatus.EN_CAMINO, TicketStatus.EN_PROGRESO,
            ])),
            kpi_resueltos=Count('pk', filter=Q(estado=TicketStatus.RESUELTO)),
            kpi_total=Count('pk'),
        )

        _estados_tecnico = (
            TicketStatus.ASIGNADO,
            TicketStatus.EN_CAMINO,
            TicketStatus.EN_PROGRESO,
            TicketStatus.RESUELTO,
            TicketStatus.CANCELADO,
        )
        ctx.update({
            'estados': (
                [c for c in TicketStatus.choices if c[0] in _estados_tecnico]
                if user.is_tecnico else TicketStatus.choices
            ),
            'estado_filtrado': self.request.GET.get('estado', ''),
            'prioridad_filtrada': self.request.GET.get('prioridad', ''),
            'search_query': self.request.GET.get('search', ''),
            **stats,
            'puede_crear': user.is_inquilino and getattr(user, 'unidad_asignada', None) is not None,
            'chatbot_habilitado': user.is_inquilino or user.is_admin,
        })
        return ctx


# ── Detalle ─────────────────────────────────────────────────────────────

class TicketDetailView(LoginRequiredMixin, DetailView):
    model = Ticket
    template_name = 'tickets/detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.select_related(
            'inquilino', 'tecnico', 'unidad', 'unidad__edificio', 'ia_tecnico_sugerido',
        ).prefetch_related('evidencias', 'historial__actor', 'mensajes__autor')

    def get_object(self, queryset=None):
        ticket = super().get_object(queryset)
        user = self.request.user
        # Control de acceso fino: inquilino solo ve los suyos, técnico solo los asignados.
        if user.is_admin or user.is_superuser:
            return ticket
        if user.is_tecnico and ticket.tecnico_id == user.id:
            return ticket
        if user.is_inquilino and ticket.inquilino_id == user.id:
            return ticket
        raise PermissionDenied('No tienes acceso a este ticket.')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ticket: Ticket = ctx['ticket']
        user = self.request.user
        actor_role = 'ADMIN' if user.is_admin else ('TECNICO' if user.is_tecnico else 'INQUILINO')
        transiciones = list(allowed_transitions_for(ticket, role=actor_role))

        # Contexto de pre-asignación para el admin
        tiene_preasignacion = (
            ticket.is_pendiente_validacion
            and ticket.ia_tecnico_sugerido is not None
        )
        tecnico_sugerido_sobrecargado = False
        if tiene_preasignacion:
            tecnico_sugerido_sobrecargado = not ticket.ia_tecnico_sugerido.puede_aceptar_ticket(
                ticket.prioridad
            )
        sin_tecnicos_disponibles = False
        if user.is_admin and ticket.is_pendiente_validacion:
            from .services.assignment import get_available_technicians
            sin_tecnicos_disponibles = not get_available_technicians(ticket.prioridad).exists()

        duracion_visita = get_visit_duration(ticket.prioridad)

        # ── Auto-agenda del inquilino (estado APROBADO) ────────────────
        puede_agendar = (
            ticket.is_aprobado
            and user.is_inquilino
            and ticket.inquilino_id == user.id
        )
        dias_disponibles = []
        dias_ocupados = []
        schedule_form = None
        primer_dia_disponible = None
        dias_postergados = 0
        sugerencia_auto = None

        if puede_agendar and ticket.tecnico:
            disponibilidad_raw = get_technician_availability_multi_day(
                ticket.tecnico, dias=14,
            )
            schedule_form = InquilinoScheduleForm(instance=ticket)

            hoy = timezone.localdate()
            for info in disponibilidad_raw:
                # Buscar grupos de N bloques consecutivos libres
                grupos = find_consecutive_free_blocks(
                    info.get('bloques', []),
                    duracion_visita,
                )
                # Cada grupo → un slot válido (primer bloque inicio, último bloque fin)
                slots_validos = []
                for grupo in grupos:
                    slots_validos.append({
                        'hora_inicio': grupo[0]['hora_inicio'],
                        'hora_fin': grupo[-1]['hora_fin'],
                        'bloques': grupo,  # los bloques individuales
                    })

                info['slots_validos'] = slots_validos

                if slots_validos:
                    dias_disponibles.append(info)
                    if primer_dia_disponible is None:
                        primer_dia_disponible = info['fecha']
                else:
                    # Razón por la que no está disponible
                    if not info['tiene_horario']:
                        info['razon'] = 'No laborable'
                    else:
                        bloques_libres = [
                            b for b in info.get('bloques', [])
                            if b.get('estado') == BLOCK_LIBRE
                        ]
                        if not bloques_libres:
                            info['razon'] = 'Agenda completa'
                        else:
                            info['razon'] = 'Sin bloques consecutivos suficientes'
                    dias_ocupados.append(info)

            if primer_dia_disponible and primer_dia_disponible != hoy:
                dias_postergados = (primer_dia_disponible - hoy).days

            sugerencia_auto = auto_suggest_schedule(ticket.tecnico, ticket.prioridad)

        # ── Chat ───────────────────────────────────────────────────────
        puede_mensajear = (
            ticket.tecnico_id is not None
            and not ticket.is_terminal
            and (
                (user.is_tecnico and ticket.tecnico_id == user.id)
                or (user.is_inquilino and ticket.inquilino_id == user.id)
            )
        )
        # Chat de coordinación en estado APROBADO
        chat_coordinacion = (
            ticket.is_aprobado
            and (
                (user.is_inquilino and ticket.inquilino_id == user.id)
                or user.is_admin
            )
        )

        ctx.update({
            'historial_estados': ticket.get_historial_para_usuario(user),
            'estado_display_user': ticket.get_estado_display_user(user),
            'transiciones_disponibles': transiciones,
            'transiciones_con_label': [
                (t, _TRANSITION_LABELS.get(t, t)) for t in transiciones
            ],
            'evidencias_reporte': ticket.evidencias.filter(momento=EvidenciaTicket.Momento.REPORTE),
            'evidencias_resolucion': ticket.evidencias.filter(momento=EvidenciaTicket.Momento.RESOLUCION),
            'transition_form': TicketTransitionForm(),
            'puede_validar': user.is_admin and ticket.is_pendiente_validacion,
            # El admin puede reasignar el técnico mientras el ticket está APROBADO
            # pero el inquilino aún no ha agendado (fecha_programada es None).
            'puede_reasignar': (
                user.is_admin
                and ticket.is_aprobado
                and ticket.fecha_programada is None
            ),
            'puede_resolver': user.is_tecnico and ticket.estado == TicketStatus.EN_PROGRESO and ticket.tecnico_id == user.id,
            'validate_form': TicketAdminValidateForm(instance=ticket),
            'reassign_form': TicketAdminValidateForm(instance=ticket),
            'resolution_form': TicketResolutionForm(instance=ticket),
            'mensajes': ticket.mensajes.all(),
            'mensaje_form': MensajeForm(),
            'puede_mensajear': puede_mensajear or chat_coordinacion,
            'chat_coordinacion': chat_coordinacion,
            # Pre-asignación admin
            'tiene_preasignacion': tiene_preasignacion,
            'tecnico_sugerido_sobrecargado': tecnico_sugerido_sobrecargado,
            'sin_tecnicos_disponibles': sin_tecnicos_disponibles,
            'peso_ticket': get_priority_weight(ticket.prioridad),
            'duracion_visita': duracion_visita,
            # Auto-agenda inquilino
            'puede_agendar': puede_agendar,
            'dias_disponibles': dias_disponibles,
            'dias_ocupados': dias_ocupados,
            'schedule_form': schedule_form,
            'primer_dia_disponible': primer_dia_disponible,
            'dias_postergados': dias_postergados,
            'sugerencia_auto': sugerencia_auto,
        })
        return ctx


# ── Creación (Inquilino) ────────────────────────────────────────────────

class TicketCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ('INQUILINO',)
    model = Ticket
    form_class = TicketCreateForm
    template_name = 'tickets/form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['inquilino'] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        titulo = self.request.GET.get('titulo', '').strip()
        descripcion = self.request.GET.get('descripcion', '').strip()
        if titulo:
            initial['titulo'] = titulo[:200]
        if descripcion:
            initial['descripcion'] = descripcion
        return initial

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_inquilino:
            unidad = getattr(request.user, 'unidad_asignada', None)
            if unidad is None:
                messages.error(request, 'No tienes una unidad asignada. Contacta al administrador.')
                return redirect('ticket_list')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['inquilino'] = self.request.user
        return kwargs

    def form_invalid(self, form):
        """Muestra errores del formulario al usuario."""
        for field, errors in form.errors.items():
            for error in errors:
                if field == '__all__':
                    messages.error(self.request, error)
                else:
                    label = form.fields[field].label or field
                    messages.error(self.request, f'{label}: {error}')
        return super().form_invalid(form)

    def form_valid(self, form):
        form.instance.inquilino = self.request.user
        response = super().form_valid(form)
        # Registramos creación en historial
        from .models import HistorialEstado
        HistorialEstado.objects.create(
            ticket=self.object,
            estado_anterior='',
            estado_nuevo=self.object.estado,
            actor=self.request.user,
            nota='Ticket creado por el residente.',
        )
        # Aviso al administrador vía n8n (async)
        try:
            from .notifications import notify_nuevo_ticket
            notify_nuevo_ticket.delay(self.object.pk)
        except Exception:
            pass

        # Notificación in-app para admin(s)
        try:
            from .services.notify import notify_ticket_created
            notify_ticket_created(self.object)
        except Exception:
            pass

        # Correo SMTP al admin
        try:
            from .services.email_service import send_ticket_created_email
            send_ticket_created_email(self.object.pk)
        except Exception:
            pass

        # Evidencias subidas en el mismo formulario
        for f in self.request.FILES.getlist('evidencias'):
            EvidenciaTicket.objects.create(
                ticket=self.object,
                archivo=f,
                momento=EvidenciaTicket.Momento.REPORTE,
                subido_por=self.request.user,
            )
        # Disparar análisis IA — async con Celery, síncrono como fallback
        try:
            from apps.ai_agent.tasks import analyze_ticket
            analyze_ticket.apply_async(args=[self.object.pk], countdown=2)
        except Exception:
            try:
                from apps.ai_agent.tasks import _run_ticket_analysis
                _run_ticket_analysis(self.object.pk)
            except Exception:
                pass  # Sin Gemini ni Celery: el admin avanza manualmente
        messages.success(self.request, f'Ticket {self.object.codigo} creado. Pronto será analizado.')
        return response

    def get_success_url(self) -> str:
        return reverse('ticket_detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Reportar Incidencia'
        ctx['button_text'] = 'Enviar Reporte'
        ctx['unidad'] = getattr(self.request.user, 'unidad_asignada', None)
        return ctx


# ── Validación (Admin) → Aprobación ─────────────────────────────────────

class TicketValidateView(RoleRequiredMixin, UpdateView):
    """Admin aprueba el ticket y asigna técnico (estado → APROBADO).

    El admin ya NO agenda la visita. Al aprobar, se notifica al inquilino
    para que él seleccione el horario desde la disponibilidad real del técnico.
    """

    allowed_roles = ('ADMIN',)
    model = Ticket
    form_class = TicketAdminValidateForm
    template_name = 'tickets/detail.html'

    def get(self, request, *args, **kwargs):
        return redirect('ticket_detail', pk=kwargs['pk'])

    def get_success_url(self) -> str:
        return reverse('ticket_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        ticket: Ticket = form.save(commit=False)
        if ticket.estado != TicketStatus.PENDIENTE_VALIDACION:
            messages.error(self.request, 'El ticket ya no se encuentra en validación.')
            return redirect('ticket_detail', pk=ticket.pk)
        if not ticket.tecnico_id:
            form.add_error('tecnico', 'Debes asignar un técnico.')
            return self.form_invalid(form)
        ticket.save()

        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.APROBADO,
                actor=self.request.user,
                actor_role='ADMIN',
                nota=(
                    f'Aprobado por {self.request.user.get_full_name()}. '
                    f'Técnico asignado: {ticket.tecnico.get_full_name()}. '
                    f'Esperando que el inquilino seleccione su horario.'
                ),
            )
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(self.request, str(exc))
            return redirect('ticket_detail', pk=ticket.pk)

        # Notificar al inquilino que su ticket fue aprobado
        try:
            from .notifications import notify_ticket_aprobado
            notify_ticket_aprobado.apply_async(args=[ticket.pk], countdown=2)
        except Exception:
            pass  # Sin Celery: el inquilino verá el estado al entrar

        # Correos SMTP: al residente (agendar cita) y al técnico (detalles)
        try:
            from .services.email_service import (
                send_ticket_approved_resident_email,
                send_ticket_approved_tech_email,
            )
            send_ticket_approved_resident_email(ticket.pk)
            send_ticket_approved_tech_email(ticket.pk)
        except Exception:
            pass

        messages.success(
            self.request,
            f'Ticket {ticket.codigo} aprobado. El inquilino recibirá una notificación para agendar.',
        )
        return redirect(self.get_success_url())


# ── Auto-agenda del Inquilino (APROBADO → ASIGNADO) ─────────────────────

class InquilinoScheduleView(LoginRequiredMixin, View):
    """El inquilino selecciona su horario de visita.

    Recibe fecha + hora desde el schedule picker y transiciona
    el ticket de APROBADO a ASIGNADO.
    """

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)

        # Validar que el inquilino sea el dueño del ticket
        if ticket.inquilino_id != request.user.id:
            raise PermissionDenied('Solo el inquilino del ticket puede agendar.')

        if ticket.estado != TicketStatus.APROBADO:
            messages.error(request, 'Este ticket ya no está disponible para agendar.')
            return redirect('ticket_detail', pk=pk)

        form = InquilinoScheduleForm(request.POST, instance=ticket)
        if not form.is_valid():
            messages.error(request, 'Por favor selecciona una fecha y hora válidas.')
            return redirect('ticket_detail', pk=pk)

        # Calcular los campos de horario en memoria, SIN guardar todavía.
        # El save() se realiza SOLO si la transición tiene éxito, evitando
        # el estado inconsistente: ticket APROBADO con fecha ya persistida.
        ticket_datos = form.save(commit=False)

        # Guard: asegurarse de que los campos de horario llegaron con valor
        if not ticket_datos.fecha_programada or not ticket_datos.hora_programada_inicio:
            messages.error(request, 'Debes seleccionar una fecha y hora de inicio válidas.')
            return redirect('ticket_detail', pk=pk)

        # Calcular hora_fin automáticamente si no fue proporcionada
        if not ticket_datos.hora_programada_fin:
            from datetime import datetime, timedelta
            duracion = get_visit_duration(ticket_datos.prioridad)
            inicio_dt = datetime.combine(ticket_datos.fecha_programada, ticket_datos.hora_programada_inicio)
            ticket_datos.hora_programada_fin = (inicio_dt + timedelta(hours=duracion)).time()

        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.ASIGNADO,
                actor=request.user,
                actor_role='INQUILINO',
                nota=(
                    f'Visita agendada por el inquilino: '
                    f'{ticket_datos.fecha_programada.strftime("%d/%m/%Y")} '
                    f'de {ticket_datos.hora_programada_inicio.strftime("%H:%M")} '
                    f'a {ticket_datos.hora_programada_fin.strftime("%H:%M")}.'
                ),
            )
        except WorkloadExceededError as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)

        # La transición fue exitosa: persistir campos de horario.
        # Refrescamos desde BD para tener el estado actualizado por transition_ticket,
        # luego escribimos solo los tres campos de horario.
        ticket.refresh_from_db()
        ticket.fecha_programada = ticket_datos.fecha_programada
        ticket.hora_programada_inicio = ticket_datos.hora_programada_inicio
        ticket.hora_programada_fin = ticket_datos.hora_programada_fin
        ticket.save(update_fields=['fecha_programada', 'hora_programada_inicio', 'hora_programada_fin'])

        # Mensaje automático de confirmación en el chat
        fecha_str = ticket.fecha_programada.strftime('%d/%m/%Y') if ticket.fecha_programada else ticket_datos.fecha_programada.strftime('%d/%m/%Y')
        inicio_str = ticket.hora_programada_inicio.strftime('%H:%M') if ticket.hora_programada_inicio else ticket_datos.hora_programada_inicio.strftime('%H:%M')
        fin_str = ticket.hora_programada_fin.strftime('%H:%M') if ticket.hora_programada_fin else ticket_datos.hora_programada_fin.strftime('%H:%M')

        MensajeTicket.objects.create(
            ticket=ticket,
            autor=request.user,
            mensaje=(
                f'He agendado la visita para el '
                f'{fecha_str} '
                f'de {inicio_str} '
                f'a {fin_str}.'
            ),
        )

        # Correo SMTP al técnico con la agenda
        try:
            from .services.email_service import send_ticket_scheduled_email
            send_ticket_scheduled_email(ticket.pk)
        except Exception:
            pass

        messages.success(
            request,
            f'Visita agendada correctamente para el {fecha_str}.',
        )
        return redirect('ticket_detail', pk=pk)


# ── Transiciones genéricas (Técnico/Admin) ─────────────────────────────

class TicketTransitionView(LoginRequiredMixin, View):
    """Endpoint POST para mover un ticket a un estado destino concreto."""

    def post(self, request: HttpRequest, pk: int, destino: str) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)
        user = request.user

        # Reglas de pertenencia
        if user.is_tecnico and ticket.tecnico_id != user.id:
            messages.error(request, 'Este ticket no está asignado a ti.')
            return redirect('ticket_detail', pk=pk)
        if user.is_inquilino and ticket.inquilino_id != user.id:
            messages.error(request, 'Acción no permitida.')
            return redirect('ticket_detail', pk=pk)

        actor_role = 'ADMIN' if user.is_admin else ('TECNICO' if user.is_tecnico else 'INQUILINO')
        nota = request.POST.get('nota', '').strip()

        try:
            transition_ticket(
                ticket,
                nuevo_estado=destino,
                actor=user,
                actor_role=actor_role,
                nota=nota,
            )
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)
        messages.success(request, f'Ticket actualizado a estado {ticket.get_estado_display()}.')
        return redirect('ticket_detail', pk=pk)


# ── Resolución (Técnico) ────────────────────────────────────────────────

class TicketResolveView(RoleRequiredMixin, View):
    """Técnico cierra el ticket: añade notas + evidencia + transición a RESUELTO."""

    allowed_roles = ('TECNICO',)

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)
        if request.user.is_tecnico and ticket.tecnico_id != request.user.id:
            messages.error(request, 'Este ticket no está asignado a ti.')
            return redirect('ticket_detail', pk=pk)

        form = TicketResolutionForm(request.POST, instance=ticket)
        if not form.is_valid():
            # Mostrar el primer error de validación del formulario
            primer_error = next(
                (e for errors in form.errors.values() for e in errors), 
                'Las notas de resolución no son válidas.'
            )
            messages.error(request, primer_error)
            return redirect('ticket_detail', pk=pk)

        # Evidencia obligatoria: el técnico debe cargar al menos un archivo
        evidencias = request.FILES.getlist('evidencias')
        if not evidencias:
            messages.error(
                request,
                'Debes adjuntar al menos una fotografía o documento como '
                'evidencia de la intervención antes de cerrar el ticket.'
            )
            return redirect('ticket_detail', pk=pk)

        form.save()

        for archivo in request.FILES.getlist('evidencias'):
            EvidenciaTicket.objects.create(
                ticket=ticket,
                archivo=archivo,
                momento=EvidenciaTicket.Momento.RESOLUCION,
                subido_por=request.user,
            )
        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.RESUELTO,
                actor=request.user,
                actor_role='ADMIN' if request.user.is_admin else 'TECNICO',
                nota='Cierre con evidencia de resolución.',
            )
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)

        # Correos SMTP al residente (resolución) y al admin (cierre del ciclo)
        try:
            from .services.email_service import (
                send_ticket_resolved_email,
                send_ticket_resolved_admin_email,
            )
            send_ticket_resolved_email(ticket.pk)
            send_ticket_resolved_admin_email(ticket.pk)
        except Exception:
            pass

        messages.success(request, f'Ticket {ticket.codigo} marcado como resuelto.')
        return redirect('ticket_detail', pk=pk)


# ── Mensajes Técnico ↔ Inquilino ───────────────────────────────────────

class MensajeCreateView(LoginRequiredMixin, View):
    """Crea un mensaje en el hilo de comunicación del ticket."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(
            Ticket.objects.select_related('inquilino', 'tecnico'),
            pk=pk,
        )
        user = request.user
        puede = (
            ticket.tecnico_id is not None
            and not ticket.is_terminal
            and (
                (user.is_tecnico and ticket.tecnico_id == user.id)
                or (user.is_inquilino and ticket.inquilino_id == user.id)
            )
        )
        if not puede:
            messages.error(request, 'No puedes enviar mensajes en este ticket.')
            return redirect('ticket_detail', pk=pk)

        form = MensajeForm(request.POST)
        if form.is_valid():
            msg = form.save(commit=False)
            msg.ticket = ticket
            msg.autor = user
            msg.save()

            # Notificación in-app para la contraparte
            try:
                from .services.notify import notify_new_message
                notify_new_message(ticket, autor=user)
            except Exception:
                pass

        if request.headers.get('HX-Request'):
            return render(request, 'tickets/partials/_mensajes.html', {
                'mensajes': ticket.mensajes.select_related('autor').all(),
                'ticket': ticket,
                'mensaje_form': MensajeForm(),
                'puede_mensajear': True,
            })

        return redirect('ticket_detail', pk=pk)


# ── Dashboard (mantener compat con URL existente) ───────────────────────

class DashboardView(LoginRequiredMixin, ListView):
    model = Ticket
    template_name = 'tickets/dashboard.html'
    context_object_name = 'tickets'
    paginate_by = 30

    def get_queryset(self):
        user = self.request.user
        qs = Ticket.objects.select_related('inquilino', 'tecnico', 'unidad__edificio')
        if user.is_admin:
            return qs
        if user.is_tecnico:
            return qs.filter(tecnico=user)
        return qs.filter(inquilino=user)

    def _scope(self):
        """Queryset base filtrado por rol para KPIs."""
        user = self.request.user
        qs = Ticket.objects.all()
        if user.is_tecnico:
            qs = qs.filter(tecnico=user)
        elif not user.is_admin:
            qs = qs.filter(inquilino=user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        scope = self._scope()

        # Una sola query con aggregate en vez de múltiples count()
        agg_kwargs = {
            'pendientes': Count('pk', filter=Q(estado__in=[
                TicketStatus.CREADO_PENDIENTE_IA,
                TicketStatus.ANALIZADO_POR_IA,
                TicketStatus.PENDIENTE_VALIDACION,
            ])),
            'en_progreso': Count('pk', filter=Q(estado__in=[
                TicketStatus.ASIGNADO,
                TicketStatus.EN_CAMINO,
                TicketStatus.EN_PROGRESO,
            ])),
            'kpi_resueltos': Count('pk', filter=Q(estado=TicketStatus.RESUELTO)),
        }
        if user.is_tecnico:
            agg_kwargs.update({
                'kpi_por_iniciar': Count('pk', filter=Q(estado=TicketStatus.ASIGNADO)),
                'kpi_en_trabajo': Count('pk', filter=Q(estado__in=[
                    TicketStatus.EN_CAMINO,
                    TicketStatus.EN_PROGRESO,
                ])),
                'kpi_resueltos_total': Count('pk', filter=Q(estado=TicketStatus.RESUELTO)),
            })

        ctx.update(scope.aggregate(**agg_kwargs))
        return ctx


# ── API AJAX: Disponibilidad de técnicos ─────────────────────────────────

class TechnicianAvailabilityView(LoginRequiredMixin, View):
    """API AJAX que retorna la disponibilidad de un técnico en JSON.

    GET /tickets/api/disponibilidad/<tecnico_id>/?fecha=YYYY-MM-DD&prioridad=MEDIA
    """

    def get(self, request: HttpRequest, tecnico_id: int) -> JsonResponse:
        if not request.user.is_admin:
            return JsonResponse({'error': 'No autorizado'}, status=403)

        tecnico = get_object_or_404(CustomUser, pk=tecnico_id, role='TECNICO')
        fecha_str = request.GET.get('fecha', '')
        prioridad = request.GET.get('prioridad', 'MEDIA')

        try:
            fecha = date.fromisoformat(fecha_str) if fecha_str else timezone.localdate()
        except ValueError:
            fecha = timezone.localdate()

        # Multi-day availability
        disponibilidad = get_technician_availability_multi_day(tecnico, desde=fecha, dias=5)

        # Auto-suggest
        sugerencia = auto_suggest_schedule(tecnico, prioridad, desde=fecha)

        # Serialize
        data = {
            'tecnico': {
                'id': tecnico.id,
                'nombre': tecnico.get_full_name(),
                'especialidades': tecnico.especialidades_display,
                'carga_actual': tecnico.carga_trabajo_actual,
                'max_carga': tecnico.max_carga_trabajo,
                'disponible_ahora': tecnico.esta_disponible_ahora(),
            },
            'dias': [
                {
                    'fecha': d['fecha'].isoformat(),
                    'dia_label': d['dia_label'],
                    'dia_label_short': d['dia_label_short'],
                    'tiene_horario': d['tiene_horario'],
                    'bloques': [
                        {
                            'hora_inicio': b['hora_inicio'].strftime('%H:%M'),
                            'hora_fin': b['hora_fin'].strftime('%H:%M'),
                            'ocupado': b.get('ocupado', b.get('estado') != 'libre'),
                            'estado': b.get('estado', 'libre'),
                            'ticket_id': b['ticket_id'],
                            'ticket_titulo': b['ticket_titulo'],
                        }
                        for b in d['bloques']
                    ],
                }
                for d in disponibilidad
            ],
            'sugerencia': {
                'fecha': sugerencia['fecha'].isoformat(),
                'hora_inicio': sugerencia['hora_inicio'].strftime('%H:%M'),
                'hora_fin': sugerencia['hora_fin'].strftime('%H:%M'),
                'duracion_horas': sugerencia['duracion_horas'],
            } if sugerencia else None,
            'duracion_visita': get_visit_duration(prioridad),
            'buffer_minutes': 30,
        }
        return JsonResponse(data)


# ── Reasignación de técnico post-aprobación (Admin) ─────────────────────

class TicketReassignView(RoleRequiredMixin, View):
    """Permite al admin cambiar el técnico asignado mientras el ticket está
    en estado APROBADO y el inquilino aún no ha agendado la visita.

    Esta vista NO cambia el estado del ticket. Solo actualiza ``ticket.tecnico``
    y registra la acción en el historial como nota. Es silenciosa (sin correos)
    para no confundir al residente con múltiples notificaciones.

    Si el nuevo técnico también está sobrecargado el form lo habrá impedido;
    aun así se valida aquí como segunda barrera.
    """

    allowed_roles = ('ADMIN',)

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        from apps.tickets.models import HistorialEstado

        ticket = get_object_or_404(Ticket, pk=pk)

        if not ticket.is_aprobado:
            messages.error(request, 'Solo se puede reasignar el técnico mientras el ticket está en estado APROBADO.')
            return redirect('ticket_detail', pk=pk)

        if ticket.fecha_programada is not None:
            messages.error(request, 'El inquilino ya agendó la visita. No se puede reasignar el técnico.')
            return redirect('ticket_detail', pk=pk)

        form = TicketAdminValidateForm(request.POST, instance=ticket)
        if not form.is_valid():
            messages.error(request, 'Datos inválidos al reasignar técnico.')
            return redirect('ticket_detail', pk=pk)

        nuevo_tecnico = form.cleaned_data.get('tecnico')
        if not nuevo_tecnico:
            messages.error(request, 'Debes seleccionar un técnico válido.')
            return redirect('ticket_detail', pk=pk)

        # Segunda barrera: verificar capacidad aunque el form lo haya deshabilitado
        if not nuevo_tecnico.puede_aceptar_ticket(ticket.prioridad):
            messages.error(
                request,
                f'{nuevo_tecnico.get_full_name()} ha alcanzado su límite de carga '
                f'({nuevo_tecnico.carga_trabajo_actual}/{nuevo_tecnico.max_carga_trabajo} puntos). '
                'Selecciona otro técnico o ajusta su límite.'
            )
            return redirect('ticket_detail', pk=pk)

        tecnico_anterior = ticket.tecnico
        ticket.tecnico = nuevo_tecnico
        ticket.save(update_fields=['tecnico', 'actualizado_en'])

        HistorialEstado.objects.create(
            ticket=ticket,
            estado_anterior=ticket.estado,
            estado_nuevo=ticket.estado,   # el estado no cambia
            actor=request.user,
            nota=(
                f'Técnico reasignado por {request.user.get_full_name()}. '
                f'Anterior: {tecnico_anterior.get_full_name() if tecnico_anterior else "(ninguno)"}. '
                f'Nuevo: {nuevo_tecnico.get_full_name()}.'
            ),
        )

        messages.success(
            request,
            f'Técnico reasignado a {nuevo_tecnico.get_full_name()} correctamente. '
            'El residente puede continuar agendando su visita.'
        )
        return redirect('ticket_detail', pk=pk)