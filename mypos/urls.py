"""
URL configuration for mypos project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from pos import views
from django.conf import settings
from django.conf.urls.static import static

from django.conf import settings
from django.conf.urls.static import static

from django.http import HttpResponse

def home(request):
    return HttpResponse("🛒 Selamat datang di MyPOS API - Backend Aktif")


urlpatterns = [
    path('', home),
    path('admin/', admin.site.urls),
    path('reports/', include('pos.report_urls')),
    path('admin/reports/', include('pos.report_urls')),
    path('reports/', include('pos.report_urls')),
    path('api/', include('pos.urls')),
    path('api/', include('pos.urls')),
    path('pos/', views.pos_kasir_view, name='pos_kasir'),
    path('order/<int:order_id>/receipt/', views.order_receipt_pdf, name='order_receipt_pdf'),
    path('pos/', views.pos_kasir_view, name='pos_kasir'),
    path('pos/remove/<int:product_id>/', views.pos_remove_from_cart, name='pos_remove_from_cart'),
    path('pos/checkout/', views.pos_checkout, name='pos_checkout'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)