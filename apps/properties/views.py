from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    UpdateView,
)

from .forms import EdificioForm, UnidadForm
from .models import Edificio, Unidad


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe la vista a usuarios con rol Administrador o superusuario."""

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and getattr(user, 'is_admin', False)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect('login')
        messages.error(self.request, 'Necesitas ser administrador para acceder a esta sección.')
        return redirect('dashboard')


# ── Edificios ────────────────────────────────────────────────────────────────

class EdificioListView(AdminRequiredMixin, ListView):
    model = Edificio
    template_name = 'properties/edificio_list.html'
    context_object_name = 'edificios'
    paginate_by = 10

    def get_queryset(self):
        qs = (
            Edificio.objects.annotate(
                unidades_total=Count('unidades'),
                unidades_libres=Count('unidades', filter=Q(unidades__inquilino__isnull=True)),
            )
            .order_by('nombre')
        )
        search = self.request.GET.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(nombre__icontains=search)
                | Q(codigo__icontains=search)
                | Q(direccion__icontains=search)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['search_query'] = self.request.GET.get('search', '')
        return ctx


class EdificioCreateView(AdminRequiredMixin, CreateView):
    model = Edificio
    form_class = EdificioForm
    template_name = 'properties/edificio_form.html'
    success_url = reverse_lazy('edificio_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Edificio "{self.object.nombre}" registrado.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Registrar Edificio'
        ctx['button_text'] = 'Crear Edificio'
        return ctx


class EdificioUpdateView(AdminRequiredMixin, UpdateView):
    model = Edificio
    form_class = EdificioForm
    template_name = 'properties/edificio_form.html'
    success_url = reverse_lazy('edificio_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Edificio "{self.object.nombre}" actualizado.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Editar Edificio'
        ctx['button_text'] = 'Guardar Cambios'
        return ctx


class EdificioDeleteView(AdminRequiredMixin, DeleteView):
    model = Edificio
    template_name = 'properties/edificio_confirm_delete.html'
    success_url = reverse_lazy('edificio_list')
    context_object_name = 'edificio'

    def form_valid(self, form):
        nombre = self.object.nombre
        response = super().form_valid(form)
        messages.success(self.request, f'Edificio "{nombre}" eliminado.')
        return response


# ── Unidades ─────────────────────────────────────────────────────────────────

class UnidadListView(AdminRequiredMixin, ListView):
    model = Unidad
    template_name = 'properties/unidad_list.html'
    context_object_name = 'unidades'
    paginate_by = 12

    def get_queryset(self):
        qs = Unidad.objects.select_related('edificio', 'inquilino').order_by('edificio__nombre', 'piso', 'numero')
        edificio_id = self.request.GET.get('edificio', '')
        ocupacion = self.request.GET.get('ocupacion', '')
        search = self.request.GET.get('search', '').strip()
        if edificio_id:
            qs = qs.filter(edificio_id=edificio_id)
        if ocupacion == 'ocupadas':
            qs = qs.filter(inquilino__isnull=False)
        elif ocupacion == 'libres':
            qs = qs.filter(inquilino__isnull=True)
        if search:
            qs = qs.filter(
                Q(numero__icontains=search)
                | Q(edificio__nombre__icontains=search)
                | Q(inquilino__first_name__icontains=search)
                | Q(inquilino__last_name__icontains=search)
                | Q(inquilino__email__icontains=search)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['edificios'] = Edificio.objects.filter(activo=True)
        ctx['edificio_filtrado'] = self.request.GET.get('edificio', '')
        ctx['ocupacion_filtrada'] = self.request.GET.get('ocupacion', '')
        ctx['search_query'] = self.request.GET.get('search', '')
        return ctx


class UnidadCreateView(AdminRequiredMixin, CreateView):
    model = Unidad
    form_class = UnidadForm
    template_name = 'properties/unidad_form.html'
    success_url = reverse_lazy('unidad_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Unidad "{self.object}" registrada.')
        return response

    def get_initial(self):
        initial = super().get_initial()
        edificio_id = self.request.GET.get('edificio')
        if edificio_id:
            initial['edificio'] = edificio_id
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Registrar Unidad'
        ctx['button_text'] = 'Crear Unidad'
        return ctx


class UnidadUpdateView(AdminRequiredMixin, UpdateView):
    model = Unidad
    form_class = UnidadForm
    template_name = 'properties/unidad_form.html'
    success_url = reverse_lazy('unidad_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Unidad "{self.object}" actualizada.')
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Editar Unidad'
        ctx['button_text'] = 'Guardar Cambios'
        return ctx


class UnidadDeleteView(AdminRequiredMixin, DeleteView):
    model = Unidad
    template_name = 'properties/unidad_confirm_delete.html'
    success_url = reverse_lazy('unidad_list')
    context_object_name = 'unidad'

    def form_valid(self, form):
        etiqueta = str(self.object)
        response = super().form_valid(form)
        messages.success(self.request, f'Unidad "{etiqueta}" eliminada.')
        return response
