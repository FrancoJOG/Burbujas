from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('burbujas.urls')),  # Incluimos las URLs de la app burbujas
] + static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])