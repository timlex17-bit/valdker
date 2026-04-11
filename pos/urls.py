from django.urls import path, include
from pos.views_shift import shifts_list, shifts_open, shifts_close
from rest_framework.routers import DefaultRouter

from . import views
from .views import (
    OrderViewSet, BannerViewSet, CustomerViewSet, SupplierViewSet,
    ProductViewSet, CategoryViewSet, UnitViewSet, ShopViewSet,
    ExpenseViewSet, DailyProfitReportAPIView, MonthlyPLReportAPIView,
    MyShopAPIView,

    StockAdjustmentViewSet,
    InventoryCountViewSet,
    ProductReturnViewSet,
    StockMovementViewSet,

    PaymentMethodViewSet,
    BankAccountViewSet,
    SalePaymentViewSet,
    BankLedgerViewSet,
    PurchaseViewSet,
    StaffViewSet,
    WarehouseViewSet,
    WarehouseStockViewSet,
    StockTransferViewSet,
)

router = DefaultRouter()
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"products", ProductViewSet, basename="product")
router.register(r"purchases", PurchaseViewSet, basename="purchases")
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"banners", BannerViewSet, basename="banner")
router.register(r"units", UnitViewSet, basename="unit")
router.register(r"orders", OrderViewSet, basename="order")
router.register(r"shops", ShopViewSet, basename="shop")
router.register(r"expenses", ExpenseViewSet, basename="expense")
router.register(r"staff", StaffViewSet, basename="staff")
router.register(r"warehouses", WarehouseViewSet, basename="warehouses")
router.register(r"warehouse-stocks", WarehouseStockViewSet, basename="warehouse-stocks")
router.register(r"stock-transfers", StockTransferViewSet, basename="stock-transfers")

router.register(r"payment-methods", PaymentMethodViewSet, basename="payment-methods")
router.register(r"bank-accounts", BankAccountViewSet, basename="bank-accounts")
router.register(r"sale-payments", SalePaymentViewSet, basename="sale-payments")
router.register(r"bank-ledgers", BankLedgerViewSet, basename="bank-ledgers")

router.register(r"stockadjustments", StockAdjustmentViewSet, basename="stockadjustments")
router.register(r"inventorycounts", InventoryCountViewSet, basename="inventorycounts")
router.register(r"productreturns", ProductReturnViewSet, basename="productreturns")
router.register(r"stockmovements", StockMovementViewSet, basename="stockmovements")

urlpatterns = [
    path("auth/login/", views.api_login, name="api_login"),
    path("auth/login", views.api_login, name="api_login_noslash"),

    path("shop/me/", MyShopAPIView.as_view(), name="my_shop"),

    path("shifts/", shifts_list, name="shifts_list"),
    path("shifts/open/", shifts_open, name="shifts_open"),
    path("shifts/<int:pk>/close/", shifts_close, name="shifts_close"),

    path("reports/daily-profit/", DailyProfitReportAPIView.as_view(), name="api_daily_profit"),
    path("reports/monthly-pl/", MonthlyPLReportAPIView.as_view(), name="api_monthly_pl"),
    path("reports/net-income-today/", views.net_income_today, name="net_income_today"),

    path("owner/", include("pos.api_owner_chat.urls")),

    path("products/print-barcodes/", views.api_print_barcodes, name="api_print_barcodes"),
    
    path("", include("pos.urls_backup")),
    
    path("", include("pos.urls_import")),

    path("", include("pos.api.urls")),
    path("", include(router.urls)),
]