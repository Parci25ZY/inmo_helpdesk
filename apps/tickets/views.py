
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import TruncDate
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
from .models import EvidenciaTicket, HistorialEstado, MensajeTicket, Ticket, TicketPriority, TicketStatus
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

logger = logging.getLogger(__name__)


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


def _errores_legibles(form) -> list[str]:
    salida: list[str] = []
    for campo, errores in form.errors.items():
        etiqueta = (
            '' if campo == '__all__'
            else f'{form.fields[campo].label or campo}: '
        )
        salida.extend(f'{etiqueta}{error}' for error in errores)
    return salida or ['Datos inválidos. Revisa el formulario.']



class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):

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



class TicketListView(LoginRequiredMixin, ListView):

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
            pass
        elif user.is_tecnico:
            qs = qs.filter(tecnico=user)
        else:
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
            'chatbot_habilitado': user.is_inquilino,
        })
        return ctx



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
                grupos = find_consecutive_free_blocks(
                    info.get('bloques', []),
                    duracion_visita,
                )
                slots_validos = []
                for grupo in grupos:
                    slots_validos.append({
                        'hora_inicio': grupo[0]['hora_inicio'],
                        'hora_fin': grupo[-1]['hora_fin'],
                        'bloques': grupo,
                    })

                info['slots_validos'] = slots_validos

                if slots_validos:
                    dias_disponibles.append(info)
                    if primer_dia_disponible is None:
                        primer_dia_disponible = info['fecha']
                else:
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

        puede_mensajear = (
            ticket.tecnico_id is not None
            and not ticket.is_terminal
            and (
                (user.is_tecnico and ticket.tecnico_id == user.id)
                or (user.is_inquilino and ticket.inquilino_id == user.id)
            )
        )
        chat_coordinacion = (
            ticket.is_aprobado
            and user.is_inquilino
            and ticket.inquilino_id == user.id
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
            'tiene_preasignacion': tiene_preasignacion,
            'tecnico_sugerido_sobrecargado': tecnico_sugerido_sobrecargado,
            'sin_tecnicos_disponibles': sin_tecnicos_disponibles,
            'peso_ticket': get_priority_weight(ticket.prioridad),
            'duracion_visita': duracion_visita,
            'puede_agendar': puede_agendar,
            'dias_disponibles': dias_disponibles,
            'dias_ocupados': dias_ocupados,
            'schedule_form': schedule_form,
            'primer_dia_disponible': primer_dia_disponible,
            'dias_postergados': dias_postergados,
            'sugerencia_auto': sugerencia_auto,
        })
        return ctx



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
        from .models import HistorialEstado
        HistorialEstado.objects.create(
            ticket=self.object,
            estado_anterior='',
            estado_nuevo=self.object.estado,
            actor=self.request.user,
            nota='Ticket creado por el residente.',
        )

        for f in self.request.FILES.getlist('evidencias'):
            EvidenciaTicket.objects.create(
                ticket=self.object,
                archivo=f,
                momento=EvidenciaTicket.Momento.REPORTE,
                subido_por=self.request.user,
            )
        try:
            from apps.ai_agent.tasks import analyze_ticket
            analyze_ticket.apply_async(args=[self.object.pk], countdown=2)
        except Exception:
            try:
                from apps.ai_agent.tasks import _run_ticket_analysis
                _run_ticket_analysis(self.object.pk)
            except Exception:
                logger.exception('Análisis IA falló para ticket %s (Celery y fallback síncrono)', self.object.pk)
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



class TicketValidateView(RoleRequiredMixin, UpdateView):

    allowed_roles = ('ADMIN',)
    model = Ticket
    form_class = TicketAdminValidateForm
    template_name = 'tickets/detail.html'

    def get(self, request, *args, **kwargs):
        return redirect('ticket_detail', pk=kwargs['pk'])

    def get_success_url(self) -> str:
        return reverse('ticket_detail', kwargs={'pk': self.object.pk})

    def form_invalid(self, form):
        for error in _errores_legibles(form):
            messages.error(self.request, error)
        return redirect('ticket_detail', pk=self.kwargs['pk'])

    def form_valid(self, form):
        ticket: Ticket = form.save(commit=False)
        if ticket.estado != TicketStatus.PENDIENTE_VALIDACION:
            messages.error(self.request, 'El ticket ya no se encuentra en validación.')
            return redirect('ticket_detail', pk=ticket.pk)

        if not ticket.tecnico_id:
            form.add_error('tecnico', 'Debes asignar un técnico antes de aprobar el ticket.')
            return self.form_invalid(form)
        if not ticket.categoria:
            form.add_error('categoria', 'Debes seleccionar una categoría.')
            return self.form_invalid(form)
        if not ticket.prioridad:
            form.add_error('prioridad', 'Debes seleccionar una prioridad.')
            return self.form_invalid(form)
        if not ticket.tecnico.puede_aceptar_ticket(ticket.prioridad):
            form.add_error(
                'tecnico',
                f'{ticket.tecnico.get_full_name()} ha alcanzado su límite de carga '
                f'({ticket.tecnico.carga_trabajo_actual}/{ticket.tecnico.max_carga_trabajo} '
                'puntos). Selecciona otro técnico o ajusta su límite.'
            )
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

        try:
            from .services.email_service import (
                send_ticket_approved_resident_email,
                send_ticket_approved_tech_email,
            )
            send_ticket_approved_resident_email(ticket.pk)
            send_ticket_approved_tech_email(ticket.pk)
        except Exception:
            logger.exception('Envío de correos de aprobación falló para ticket %s', ticket.pk)

        messages.success(
            self.request,
            f'Ticket {ticket.codigo} aprobado. El inquilino recibirá una notificación para agendar.',
        )
        return redirect(self.get_success_url())



class InquilinoScheduleView(LoginRequiredMixin, View):

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)

        if ticket.inquilino_id != request.user.id:
            raise PermissionDenied('Solo el inquilino del ticket puede agendar.')

        if ticket.estado != TicketStatus.APROBADO:
            messages.error(request, 'Este ticket ya no está disponible para agendar.')
            return redirect('ticket_detail', pk=pk)

        form = InquilinoScheduleForm(request.POST, instance=ticket)
        if not form.is_valid():
            messages.error(request, 'Por favor selecciona una fecha y hora válidas.')
            return redirect('ticket_detail', pk=pk)

        fecha_programada = form.cleaned_data.get('fecha_programada')
        hora_programada_inicio = form.cleaned_data.get('hora_programada_inicio')
        hora_programada_fin = form.cleaned_data.get('hora_programada_fin')

        if not fecha_programada or not hora_programada_inicio:
            messages.error(request, 'Debes seleccionar una fecha y hora de inicio válidas.')
            return redirect('ticket_detail', pk=pk)

        if not hora_programada_fin:
            from datetime import datetime, timedelta
            duracion = get_visit_duration(ticket.prioridad)
            inicio_dt = datetime.combine(fecha_programada, hora_programada_inicio)
            hora_programada_fin = (inicio_dt + timedelta(hours=duracion)).time()

        try:
            transition_ticket(
                ticket,
                nuevo_estado=TicketStatus.ASIGNADO,
                actor=request.user,
                actor_role='INQUILINO',
                nota=(
                    f'Visita agendada por el inquilino: '
                    f'{fecha_programada.strftime("%d/%m/%Y")} '
                    f'de {hora_programada_inicio.strftime("%H:%M")} '
                    f'a {hora_programada_fin.strftime("%H:%M")}.'
                ),
            )
        except WorkloadExceededError as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(request, str(exc))
            return redirect('ticket_detail', pk=pk)

        ticket.refresh_from_db()
        ticket.fecha_programada = fecha_programada
        ticket.hora_programada_inicio = hora_programada_inicio
        ticket.hora_programada_fin = hora_programada_fin
        ticket.save(update_fields=['fecha_programada', 'hora_programada_inicio', 'hora_programada_fin'])

        fecha_str = fecha_programada.strftime('%d/%m/%Y')
        inicio_str = hora_programada_inicio.strftime('%H:%M')
        fin_str = hora_programada_fin.strftime('%H:%M')

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

        try:
            from .services.email_service import send_ticket_scheduled_email
            send_ticket_scheduled_email(ticket.pk)
        except Exception:
            logger.exception('Envío de correo de agenda falló para ticket %s', ticket.pk)

        messages.success(
            request,
            f'Visita agendada correctamente para el {fecha_str}.',
        )
        return redirect('ticket_detail', pk=pk)



class TicketTransitionView(LoginRequiredMixin, View):

    _REQUIERE_FORMULARIO_DEDICADO = {
        (TicketStatus.PENDIENTE_VALIDACION, TicketStatus.APROBADO),
        (TicketStatus.APROBADO, TicketStatus.ASIGNADO),
        (TicketStatus.EN_PROGRESO, TicketStatus.RESUELTO),
    }

    def post(self, request: HttpRequest, pk: int, destino: str) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)
        user = request.user

        if (ticket.estado, destino) in self._REQUIERE_FORMULARIO_DEDICADO:
            messages.error(
                request,
                'Esta transición requiere información adicional; usa el '
                'formulario correspondiente en la ficha del ticket.',
            )
            return redirect('ticket_detail', pk=pk)

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



class TicketResolveView(RoleRequiredMixin, View):

    allowed_roles = ('TECNICO',)

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)
        if request.user.is_tecnico and ticket.tecnico_id != request.user.id:
            messages.error(request, 'Este ticket no está asignado a ti.')
            return redirect('ticket_detail', pk=pk)

        form = TicketResolutionForm(request.POST, instance=ticket)
        if not form.is_valid():
            primer_error = next(
                (e for errors in form.errors.values() for e in errors), 
                'Las notas de resolución no son válidas.'
            )
            messages.error(request, primer_error)
            return redirect('ticket_detail', pk=pk)

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

        try:
            from .services.email_service import (
                send_ticket_resolved_email,
                send_ticket_resolved_admin_email,
            )
            send_ticket_resolved_email(ticket.pk)
            send_ticket_resolved_admin_email(ticket.pk)
        except Exception:
            logger.exception('Envío de correos de resolución falló para ticket %s', ticket.pk)

        messages.success(request, f'Ticket {ticket.codigo} marcado como resuelto.')
        return redirect('ticket_detail', pk=pk)



class MensajeCreateView(LoginRequiredMixin, View):

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

            try:
                from .services.notify import notify_new_message
                notify_new_message(ticket, autor=user)
            except Exception:
                logger.exception('notify_new_message falló para ticket %s', ticket.pk)

        if request.headers.get('HX-Request'):
            return render(request, 'tickets/partials/_mensajes.html', {
                'mensajes': ticket.mensajes.select_related('autor').all(),
                'ticket': ticket,
                'mensaje_form': MensajeForm(),
                'puede_mensajear': True,
            })

        return redirect('ticket_detail', pk=pk)



def _sparkline_coords(valores: list[int], *, ancho: int = 104, alto: int = 32, relleno: int = 4) -> list[tuple[float, float]]:
    if not valores:
        return []
    maximo, minimo = max(valores), min(valores)
    rango = (maximo - minimo) or 1
    n = len(valores)
    paso_x = ancho / (n - 1) if n > 1 else 0
    return [
        (round(i * paso_x, 1), round(relleno + (alto - 2 * relleno) * (1 - (v - minimo) / rango), 1))
        for i, v in enumerate(valores)
    ]


def _stat_tile_trend(serie_semana_actual: list[int], total_semana_previa: int, *, bueno_si_baja: bool | None) -> dict:
    coords = _sparkline_coords(serie_semana_actual)
    total_actual = sum(serie_semana_actual)
    delta = total_actual - total_semana_previa
    delta_pct = round(delta / total_semana_previa * 100) if total_semana_previa > 0 else None

    if bueno_si_baja is None or delta == 0:
        color = 'text-zinc-500'
    elif (delta > 0) != bueno_si_baja:
        color = 'text-emerald-600'
    else:
        color = 'text-red-600'

    ultimo_x, ultimo_y = coords[-1] if coords else (0, 0)
    return {
        'polyline': ' '.join(f'{x},{y}' for x, y in coords),
        'ultimo_x': f'{ultimo_x}',
        'ultimo_y': f'{ultimo_y}',
        'total_actual': total_actual,
        'delta': delta,
        'delta_pct': delta_pct,
        'color': color,
    }


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

        if not user.is_tecnico:
            ctx['kpi_tendencias'] = self._tendencias_semanales(scope)

        return ctx

    def _tendencias_semanales(self, scope) -> dict:
        hoy = timezone.localdate()
        dias = [hoy - timedelta(days=i) for i in range(6, -1, -1)]
        inicio_ventana = dias[0]
        inicio_semana_previa = inicio_ventana - timedelta(days=7)

        def _serie_por_fecha(queryset, campo_fecha):
            filas = (
                queryset
                .filter(**{f'{campo_fecha}__date__gte': inicio_semana_previa})
                .annotate(dia=TruncDate(campo_fecha))
                .values('dia')
                .annotate(n=Count('pk'))
            )
            por_dia = {fila['dia']: fila['n'] for fila in filas}
            semana_actual = [por_dia.get(d, 0) for d in dias]
            semana_previa_total = sum(n for d, n in por_dia.items() if d < inicio_ventana)
            return semana_actual, semana_previa_total

        creados, creados_prev = _serie_por_fecha(scope, 'creado_en')
        resueltos, resueltos_prev = _serie_por_fecha(
            scope.filter(resuelto_en__isnull=False), 'resuelto_en',
        )
        asignados, asignados_prev = _serie_por_fecha(
            HistorialEstado.objects.filter(ticket__in=scope, estado_nuevo=TicketStatus.ASIGNADO),
            'creado_en',
        )

        return {
            'pendientes': _stat_tile_trend(creados, creados_prev, bueno_si_baja=True),
            'en_progreso': _stat_tile_trend(asignados, asignados_prev, bueno_si_baja=None),
            'resueltos': _stat_tile_trend(resueltos, resueltos_prev, bueno_si_baja=False),
        }



class TechnicianAvailabilityView(LoginRequiredMixin, View):

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

        disponibilidad = get_technician_availability_multi_day(tecnico, desde=fecha, dias=5)

        sugerencia = auto_suggest_schedule(tecnico, prioridad, desde=fecha)

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



class TicketReassignView(RoleRequiredMixin, View):

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
            for error in _errores_legibles(form):
                messages.error(request, error)
            return redirect('ticket_detail', pk=pk)

        nuevo_tecnico = form.cleaned_data.get('tecnico')
        if not nuevo_tecnico:
            messages.error(request, 'Debes seleccionar un técnico válido.')
            return redirect('ticket_detail', pk=pk)

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
            estado_nuevo=ticket.estado,
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