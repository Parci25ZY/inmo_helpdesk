from django.shortcuts import render
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Ticket

class DashboardView(LoginRequiredMixin, ListView):
    """
    Vista principal del sistema. 
    Filtra los tickets según el rol del usuario autenticado.
    """
    model = Ticket
    template_name = 'tickets/dashboard.html'
    context_object_name = 'tickets'

    def get_queryset(self):
        user = self.request.user
        if user.rol == user.Roles.TECNICO:
            return Ticket.objects.all().select_related('inquilino', 'tecnico')
        else:
            return Ticket.objects.filter(inquilino=user).select_related('tecnico')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()
        context['pendientes'] = queryset.filter(estado='PENDIENTE').count()
        context['en_progreso'] = queryset.filter(estado='EN_PROGRESO').count()
        return context
