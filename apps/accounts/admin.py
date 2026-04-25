from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from django.utils.translation import gettext_lazy as _

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Configuración profesional del panel de administración para usuarios.
    """
    # Columnas que verás en el listado principal
    list_display = ('username', 'email', 'get_full_name', 'rol', 'is_staff', 'date_joined')
    
    # Filtros laterales para encontrar gente rápido
    list_filter = ('rol', 'is_staff', 'is_superuser', 'is_active')
    
    # Buscador por campos clave
    search_fields = ('username', 'first_name', 'last_name', 'email')
    
    # Orden predeterminado (más recientes primero)
    ordering = ('-date_joined',)

    # Organización de los formularios de edición/creación
    fieldsets = UserAdmin.fieldsets + (
        (_('Información de InmoHelpdesk'), {'fields': ('rol', 'telefono')}),
    )
    
    # Formulario para crear usuarios nuevos
    add_fieldsets = UserAdmin.add_fieldsets + (
        (_('Información de InmoHelpdesk'), {
            'classes': ('wide',),
            'fields': ('rol', 'telefono'),
        }),
    )