from django.contrib import admin
from .models import Ticket

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'inquilino', 'tecnico', 'estado', 'prioridad', 'creado_en')
    list_filter = ('estado', 'prioridad', 'creado_en')
    search_fields = ('titulo', 'descripcion', 'inquilino__username')
    list_editable = ('estado', 'prioridad', 'tecnico')