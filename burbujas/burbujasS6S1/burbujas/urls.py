from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('servidores-publicos/', views.lista_servidores_publicos, name='lista_servidores_publicos'),
    path('empresas/', views.empresas_chart_view, name='empresas_chart'),
    path('cruces_s1_s6/', views.cruces_s1_s6_view, name='cruces_s1_s6'),
    path('mapa_mexico/', views.mapa_mexico_view, name='mapa_mexico'),
    path('filtros_dinamicos/', views.filtros_dinamicos, name='filtros_dinamicos'),
]
