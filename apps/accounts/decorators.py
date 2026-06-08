from django.core.exceptions import PermissionDenied
from functools import wraps
from django.shortcuts import redirect

def role_required(*roles):
    """
    Decorador para verificar que el usuario tiene uno de los roles requeridos.
    Uso: @role_required('ADMIN', 'TECNICO')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            # Superusuarios siempre tienen acceso
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Verificar si el rol del usuario está en la lista permitida
            if hasattr(request.user, 'role') and request.user.role in roles:
                return view_func(request, *args, **kwargs)
            
            raise PermissionDenied("No tienes permisos para acceder a esta página.")
        
        return wrapped_view
    return decorator

def admin_required(view_func):
    """
    Decorador para verificar que el usuario es administrador.
    Uso: @admin_required
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        # Usamos la propiedad .is_admin de nuestro CustomUser
        if getattr(request.user, 'is_admin', False):
            return view_func(request, *args, **kwargs)
        
        raise PermissionDenied("Necesitas ser administrador para acceder a esta página.")
    
    return wrapped_view

def tecnico_or_admin_required(view_func):
    """
    Decorador para verificar que el usuario es técnico o administrador.
    """
    return role_required('ADMIN', 'TECNICO')(view_func)

def inquilino_or_admin_required(view_func):
    """
    Decorador para verificar que el usuario es inquilino o administrador.
    """
    return role_required('ADMIN', 'INQUILINO')(view_func)
