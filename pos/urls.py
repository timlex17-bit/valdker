from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.contrib import admin

from . import views
from .views import (
    OrderViewSet, BannerViewSet, CustomerViewSet, SupplierViewSet,
    ProductViewSet, CategoryViewSet, UnitViewSet, ShopViewSet,
    ExpenseViewSet, DailyProfitReportAPIView, MonthlyPLReportAPIView,

    # ✅ inventory viewsets
    StockAdjustmentViewSet,
    InventoryCountViewSet,
    ProductReturnViewSet,
    StockMovementViewSet,
)

router = DefaultRouter()
router.register(r"customers", CustomerViewSet)
router.register(r"suppliers", SupplierViewSet)
router.register(r"products", ProductViewSet)
router.register(r"categories", CategoryViewSet)
router.register(r"banners", BannerViewSet)
router.register(r"units", UnitViewSet)
router.register(r"orders", OrderViewSet)
router.register(r"shops", ShopViewSet)
router.register(r"expenses", ExpenseViewSet)

# ✅ NEW: Inventory APIs
router.register(r"stockadjustments", StockAdjustmentViewSet, basename="stockadjustments")
router.register(r"inventorycounts", InventoryCountViewSet, basename="inventorycounts")
router.register(r"productreturns", ProductReturnViewSet, basename="productreturns")
router.register(r"stockmovements", StockMovementViewSet, basename="stockmovements")

urlpatterns = [
    # auth
    path("auth/login/", views.api_login, name="api_login"),
    path("auth/login", views.api_login, name="api_login_noslash"),

    # reports
    path("reports/daily-profit/", DailyProfitReportAPIView.as_view(), name="api_daily_profit"),
    path("reports/monthly-pl/", MonthlyPLReportAPIView.as_view(), name="api_monthly_pl"),
    path("reports/net-income-today/", views.net_income_today, name="net_income_today"),

    # barcode pdf (API)
    path("products/print-barcodes/", views.api_print_barcodes, name="api_print_barcodes"),

    # router urls
    path("", include(router.urls)),
]