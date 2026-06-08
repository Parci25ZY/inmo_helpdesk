from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, EmailVerificationCode
from .forms import UserCreateForm, UserEditForm

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # Usar los formularios personalizados estilizados
    add_form = UserCreateForm
    form = UserEditForm
    model = CustomUser
    
    # Configuración de la lista
    list_display = ['email', 'first_name', 'last_name', 'role', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['role', 'is_active', 'is_staff', 'date_joined']
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering = ['-date_joined']
    
    # Organización de los campos al editar
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Información Personal', {'fields': ('first_name', 'last_name', 'phone')}),
        ('Rol y Permisos', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas Importantes', {'fields': ('date_joined', 'last_login')}),
    )
    
    # Organización de los campos al crear un nuevo usuario
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone', 'role', 'is_staff', 'is_active'),
        }),
    )
    
    readonly_fields = ['date_joined', 'last_login']


@admin.register(EmailVerificationCode)
class EmailVerificationCodeAdmin(admin.ModelAdmin):
    list_display = ('email', 'code', 'purpose', 'is_used', 'verified_at', 'expires_at', 'created_at')
    list_filter = ('purpose', 'is_used')
    search_fields = ('email', 'code')
    readonly_fields = ('created_at', 'verified_at')
