from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods

from .models import CustomUser
from .forms import (
    CustomUserCreationForm, 
    CustomAuthenticationForm, 
    UserEditForm, 
    UserCreateForm,
    ProfileEditForm,
)
from .decorators import admin_required

def user_login(request):
    """Vista de inicio de sesión"""
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            email = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            # Cambiamos email=email por username=email para mayor compatibilidad
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Bienvenido de nuevo, {user.first_name}.')
                return redirect('dashboard')
            else:
                messages.error(request, 'Correo o contraseña incorrectos.')
    else:
        form = CustomAuthenticationForm()
    return render(request, 'accounts/login.html', {'form': form})


def password_reset_confirm_page(request):
    """Página para establecer nueva contraseña tras verificar el correo."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'accounts/password_reset_confirm.html')


@require_http_methods(["GET", "POST"])
def user_logout(request):
    """Cerrar sesión (Soporta GET y POST para mayor compatibilidad)"""
    logout(request)
    messages.info(request, 'Has cerrado sesión correctamente.')
    return redirect('login')

@admin_required
def user_list(request):
    """Listado de usuarios con búsqueda y filtrado (Solo Admin)"""
    search_query = request.GET.get('search', '')
    role_filter = request.GET.get('role', '')
    
    users = CustomUser.objects.all()
    
    if search_query:
        users = users.filter(
            models.Q(first_name__icontains=search_query) |
            models.Q(last_name__icontains=search_query) |
            models.Q(email__icontains=search_query)
        )
    
    if role_filter:
        users = users.filter(role=role_filter)
    
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'role_filter': role_filter,
        'role_choices': CustomUser.Roles.choices,
    }
    return render(request, 'accounts/user_list.html', context)

@admin_required
def user_create(request):
    """Creación de nuevos usuarios por el administrador"""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'Usuario {user.get_full_name()} creado exitosamente.')
            return redirect('user_list')
    else:
        form = UserCreateForm()
    
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': 'Crear Usuario',
        'button_text': 'Crear Usuario'
    })

@admin_required
def user_edit(request, user_id):
    """Edición de usuarios existentes por el administrador"""
    user = get_object_or_404(CustomUser, id=user_id)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Usuario {user.get_full_name()} actualizado.')
            return redirect('user_list')
    else:
        form = UserEditForm(instance=user)
    
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'user_obj': user,
        'title': 'Editar Usuario',
        'button_text': 'Guardar Cambios'
    })

@admin_required
def user_delete(request, user_id):
    """Eliminación de usuarios por el administrador"""
    user = get_object_or_404(CustomUser, id=user_id)
    
    if request.user.id == user.id:
        messages.error(request, 'No puedes eliminar tu propia cuenta.')
        return redirect('user_list')
    
    if request.method == 'POST':
        nombre = user.get_full_name()
        user.delete()
        messages.success(request, f'Usuario {nombre} eliminado correctamente.')
        return redirect('user_list')
    
    return render(request, 'accounts/user_confirm_delete.html', {'user_obj': user})

@login_required
def user_profile(request):
    """Perfil del usuario autenticado.

    Usa ProfileEditForm que solo expone campos seguros (nombre, email, teléfono).
    No permite cambiar rol, is_active, is_staff ni especialidad.
    """
    if request.method == 'POST':
        form = ProfileEditForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Perfil actualizado exitosamente.')
            return redirect('user_profile')
    else:
        form = ProfileEditForm(instance=request.user)
    
    return render(request, 'accounts/user_profile.html', {'form': form})
