from django.urls import path

from . import views

urlpatterns = [
    # Edificios
    path('edificios/', views.EdificioListView.as_view(), name='edificio_list'),
    path('edificios/crear/', views.EdificioCreateView.as_view(), name='edificio_create'),
    path('edificios/<int:pk>/editar/', views.EdificioUpdateView.as_view(), name='edificio_edit'),
    path('edificios/<int:pk>/eliminar/', views.EdificioDeleteView.as_view(), name='edificio_delete'),

    # Unidades
    path('unidades/', views.UnidadListView.as_view(), name='unidad_list'),
    path('unidades/crear/', views.UnidadCreateView.as_view(), name='unidad_create'),
    path('unidades/<int:pk>/editar/', views.UnidadUpdateView.as_view(), name='unidad_edit'),
    path('unidades/<int:pk>/eliminar/', views.UnidadDeleteView.as_view(), name='unidad_delete'),
]
