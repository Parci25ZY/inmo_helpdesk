from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.user_login, name='login'),
    path('recuperar-contrasena/', views.password_reset_confirm_page, name='password_reset_confirm'),
    path('logout/', views.user_logout, name='logout'),
    path('profile/', views.user_profile, name='user_profile'),

    # Gestión de usuarios (Solo Admin)
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user_delete'),
]
