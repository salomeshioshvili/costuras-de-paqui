from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views

admin.site.site_header = "Costuras de Paqui"
admin.site.site_title = "Costuras de Paqui"
admin.site.index_title = "Site administration"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('shop.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
