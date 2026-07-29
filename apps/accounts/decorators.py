from django.core.exceptions import PermissionDenied
from functools import wraps
from django.shortcuts import redirect

def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            if hasattr(request.user, 'role') and request.user.role in roles:
                return view_func(request, *args, **kwargs)
            
            raise PermissionDenied("No tienes permisos para acceder a esta página.")
        
        return wrapped_view
    return decorator

def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if getattr(request.user, 'is_admin', False):
            return view_func(request, *args, **kwargs)
        
        raise PermissionDenied("Necesitas ser administrador para acceder a esta página.")
    
    return wrapped_view

def tecnico_or_admin_required(view_func):
    return role_required('ADMIN', 'TECNICO')(view_func)

def inquilino_or_admin_required(view_func):
    return role_required('ADMIN', 'INQUILINO')(view_func)
