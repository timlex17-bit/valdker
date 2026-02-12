from django.urls import path, include
from .views import ShopViewSet
from rest_framework.routers import DefaultRouter

from . import views
from .views import (
    OrderViewSet,
    BannerViewSet,
    CustomerViewSet,
    SupplierViewSet,
    ProductViewSet,
    CategoryViewSet,
    UnitViewSet,
)

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'suppliers', SupplierViewSet)
router.register(r'products', ProductViewSet)  
router.register(r'categories', CategoryViewSet)
router.register(r'banners', BannerViewSet)
router.register(r'units', UnitViewSet)
router.register(r'orders', OrderViewSet)
router.register(r"shops", ShopViewSet)

urlpatterns = [
    path("auth/login/", views.api_login, name="api_login"),
    path("auth/login", views.api_login, name="api_login_noslash"),
    path("shop/", views.ShopPublicView.as_view()),
    path("", include(router.urls)),
]
