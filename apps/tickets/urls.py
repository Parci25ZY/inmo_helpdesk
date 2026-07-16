from django.urls import path

from . import api, views

urlpatterns = [
    path('', views.TicketListView.as_view(), name='ticket_list'),
    path('crear/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('<int:pk>/validar/', views.TicketValidateView.as_view(), name='ticket_validate'),
    path('<int:pk>/agendar/', views.InquilinoScheduleView.as_view(), name='ticket_schedule'),
    path('<int:pk>/reasignar/', views.TicketReassignView.as_view(), name='ticket_reassign'),
    path('<int:pk>/resolver/', views.TicketResolveView.as_view(), name='ticket_resolve'),
    path('<int:pk>/transicion/<str:destino>/', views.TicketTransitionView.as_view(), name='ticket_transition'),
    path('<int:pk>/mensaje/', views.MensajeCreateView.as_view(), name='ticket_mensaje_create'),
    # API AJAX
    path('api/disponibilidad/<int:tecnico_id>/', views.TechnicianAvailabilityView.as_view(), name='api_technician_availability'),
    path('api/notificaciones/', api.notificaciones_list, name='api_notificaciones_list'),
    path('api/notificaciones/marcar-leidas/', api.notificaciones_marcar_leidas, name='api_notificaciones_marcar_leidas'),
]

