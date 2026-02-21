from django.contrib import admin
from django.urls import path, include
from pos.views_owner_chat import OwnerChatAPIView
from pos import views
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

def home(request):
    return HttpResponse("🛒 Selamat datang di MyPOS API - Backend Aktif")

urlpatterns = [
    path("", home),

    # ✅ barcode print (HARUS sebelum admin/)
    path("admin/print-barcodes/", admin.site.admin_view(views.admin_print_barcodes), name="admin_print_barcodes"),
    
    path("api/owner/chat/", OwnerChatAPIView.as_view(), name="owner-chat"),

    # ✅ reports (wajib sebelum admin/)
    path("admin/reports/sales/", admin.site.admin_view(views.sales_report_view), name="admin_sales_report"),
    path("admin/reports/expense/", admin.site.admin_view(views.expense_report_view), name="admin_expense_report"),
    path("admin/reports/sales-chart/", admin.site.admin_view(views.sales_chart_view), name="admin_sales_chart"),
    path("admin/reports/expense-chart/", admin.site.admin_view(views.expense_chart_view), name="admin_expense_chart"),
    path("admin/reports/", include("pos.report_urls")),

    # ✅ admin
    path("admin/", admin.site.urls),

    # ✅ web POS kasir
    path("pos/", views.pos_kasir_view, name="pos_kasir"),
    path("pos/remove/<int:product_id>/", views.pos_remove_from_cart, name="pos_remove_from_cart"),
    path("pos/checkout/", views.pos_checkout, name="pos_checkout"),

    # ✅ receipt
    path("order/<int:order_id>/receipt/", views.order_receipt_pdf, name="order_receipt_pdf"),

    # ✅ API
    path("api/", include("pos.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
