from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.tickets.views import DashboardView

urlpatterns = [
    path('admin/', admin.site.urls),

    # ── Home público y dashboard autenticado ──
    path('', TemplateView.as_view(template_name='base.html'), name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # ── Autenticación y cuentas (login, perfil, gestión de usuarios) ──
    path('', include('apps.accounts.urls')),

    # ── Tickets (core operativo) ──
    path('tickets/', include('apps.tickets.urls')),

    # ── Inmuebles (edificios y unidades) ──
    path('inventario/', include('apps.properties.urls')),

    # ── API IA / Chatbot (DRF) ──
    path('api/', include('apps.ai_agent.urls')),

    # ── API Autenticación JWT ──
    path('api/auth/', include('apps.accounts.api_urls')),

    # ── Devtools ──
    path('__reload__/', include('django_browser_reload.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
