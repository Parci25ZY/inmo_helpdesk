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

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    View,
)

from apps.accounts.models import CustomUser

from .forms import (
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
    allowed_transitions_for,
    transition_ticket,
)


# Labels legibles para cada transición — reemplaza el enum crudo en la UI
_TRANSITION_LABELS: dict[str, str] = {
    TicketStatus.ANALIZADO_POR_IA: 'Marcar como analizado',
    TicketStatus.PENDIENTE_VALIDACION: 'Enviar a validación',
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
        ctx.update({
            'transiciones_disponibles': transiciones,
            'transiciones_con_label': [
                (t, _TRANSITION_LABELS.get(t, t)) for t in transiciones
            ],
            'evidencias_reporte': ticket.evidencias.filter(momento=EvidenciaTicket.Momento.REPORTE),
            'evidencias_resolucion': ticket.evidencias.filter(momento=EvidenciaTicket.Momento.RESOLUCION),
            'transition_form': TicketTransitionForm(),
            'puede_validar': user.is_admin and ticket.is_pendiente_validacion,
            'puede_resolver': user.is_tecnico and ticket.estado == TicketStatus.EN_PROGRESO and ticket.tecnico_id == user.id,
            'validate_form': TicketAdminValidateForm(instance=ticket),
            'resolution_form': TicketResolutionForm(instance=ticket),
            'mensajes': ticket.mensajes.all(),
            'mensaje_form': MensajeForm(),
            'puede_mensajear': (
                ticket.tecnico_id is not None
                and not ticket.is_terminal
                and (
                    (user.is_tecnico and ticket.tecnico_id == user.id)
                    or (user.is_inquilino and ticket.inquilino_id == user.id)
                )
            ),
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


# ── Validación (Admin) ──────────────────────────────────────────────────

class TicketValidateView(RoleRequiredMixin, UpdateView):
    """Admin valida sugerencia IA y asigna técnico (estado → ASIGNADO)."""

    allowed_roles = ('ADMIN',)
    model = Ticket
    form_class = TicketAdminValidateForm
    template_name = 'tickets/detail.html'

    def get(self, request, *args, **kwargs):
        # El form vive embebido en detail.html, así que redirigimos.
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
                nuevo_estado=TicketStatus.ASIGNADO,
                actor=self.request.user,
                actor_role='ADMIN',
                nota=f'Asignado a {ticket.tecnico.get_full_name()}.',
            )
        except (InvalidTransitionError, TransitionPermissionError) as exc:
            messages.error(self.request, str(exc))
            return redirect('ticket_detail', pk=ticket.pk)
        messages.success(self.request, f'Ticket {ticket.codigo} validado y asignado.')
        return redirect(self.get_success_url())


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

    allowed_roles = ('TECNICO', 'ADMIN')

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        ticket = get_object_or_404(Ticket, pk=pk)
        if request.user.is_tecnico and ticket.tecnico_id != request.user.id:
            messages.error(request, 'Este ticket no está asignado a ti.')
            return redirect('ticket_detail', pk=pk)

        form = TicketResolutionForm(request.POST, instance=ticket)
        if not form.is_valid():
            messages.error(request, 'Las notas de resolución son obligatorias.')
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
