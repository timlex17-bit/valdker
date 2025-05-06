from django.urls import path, include
from .views import OrderViewSet
from .views import BannerViewSet

from .views import BannerListView
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, SupplierViewSet, ProductViewSet, CategoryViewSet, UnitViewSet

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'suppliers', SupplierViewSet)
router.register(r'products', ProductViewSet)
router.register(r'categories', CategoryViewSet)
router.register(r'banners', BannerViewSet)
router.register(r'units', UnitViewSet)
router.register(r'orders', OrderViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
