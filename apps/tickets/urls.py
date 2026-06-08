from django.urls import path

from . import views

urlpatterns = [
    path('', views.TicketListView.as_view(), name='ticket_list'),
    path('crear/', views.TicketCreateView.as_view(), name='ticket_create'),
    path('<int:pk>/', views.TicketDetailView.as_view(), name='ticket_detail'),
    path('<int:pk>/validar/', views.TicketValidateView.as_view(), name='ticket_validate'),
    path('<int:pk>/resolver/', views.TicketResolveView.as_view(), name='ticket_resolve'),
    path('<int:pk>/transicion/<str:destino>/', views.TicketTransitionView.as_view(), name='ticket_transition'),
    path('<int:pk>/evidencia/', views.EvidenciaUploadView.as_view(), name='ticket_evidencia_upload'),
]
