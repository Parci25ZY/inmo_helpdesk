from django.contrib import admin

from .models import EvidenciaTicket, HistorialEstado, Ticket


class EvidenciaInline(admin.TabularInline):
    model = EvidenciaTicket
    extra = 0
    readonly_fields = ('creado_en', 'subido_por')


class HistorialInline(admin.TabularInline):
    model = HistorialEstado
    extra = 0
    readonly_fields = ('estado_anterior', 'estado_nuevo', 'actor', 'nota', 'creado_en')
    can_delete = False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'unidad', 'inquilino', 'tecnico', 'estado', 'prioridad', 'creado_en')
    list_filter = ('estado', 'prioridad', 'categoria', 'creado_en')
    search_fields = ('titulo', 'descripcion', 'inquilino__email', 'unidad__numero')
    autocomplete_fields = ('unidad', 'inquilino', 'tecnico', 'ia_tecnico_sugerido')
    readonly_fields = ('creado_en', 'actualizado_en', 'resuelto_en')
    inlines = [EvidenciaInline, HistorialInline]


@admin.register(HistorialEstado)
class HistorialEstadoAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'estado_anterior', 'estado_nuevo', 'actor', 'creado_en')
    list_filter = ('estado_nuevo', 'creado_en')
    readonly_fields = ('ticket', 'estado_anterior', 'estado_nuevo', 'actor', 'nota', 'creado_en')
