from django.contrib import admin

from .models import Edificio, Unidad


class UnidadInline(admin.TabularInline):
    model = Unidad
    extra = 0
    fields = ('numero', 'piso', 'tipo', 'inquilino', 'activo')
    autocomplete_fields = ('inquilino',)


@admin.register(Edificio)
class EdificioAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'ciudad', 'total_unidades', 'unidades_ocupadas', 'activo')
    list_filter = ('ciudad', 'activo')
    search_fields = ('nombre', 'codigo', 'direccion')
    inlines = [UnidadInline]
    readonly_fields = ('creado_en', 'actualizado_en')


@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display = ('edificio', 'numero', 'piso', 'tipo', 'inquilino', 'activo')
    list_filter = ('edificio', 'tipo', 'activo', 'piso')
    search_fields = ('numero', 'edificio__nombre', 'edificio__codigo', 'inquilino__email')
    autocomplete_fields = ('edificio', 'inquilino')
    readonly_fields = ('creado_en', 'actualizado_en')
