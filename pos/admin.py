from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from pos.models_shift import Shift
from reportlab.graphics.barcode import code128

from .models import (
    Banner, TokenProxy, CustomUser,
    Customer, Supplier, Category, Unit,
    Product, Order, OrderItem, Expense, Shop,
    StockAdjustment, InventoryCount, InventoryCountItem,
    ProductReturn, ProductReturnItem, StockMovement
)


# ==========================================================
# PDF Barcode Printing (Admin)
# ==========================================================
def _barcode_pdf_response(filename="barcodes.pdf"):
    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{filename}"'
    return resp


def print_barcodes_pdf(modeladmin, request, queryset):
    """
    Admin action: print selected products barcode labels into a PDF.
    Uses Product.code as barcode value, and Product.sku as optional text.
    """
    resp = _barcode_pdf_response("product_barcodes.pdf")
    c = canvas.Canvas(resp, pagesize=A4)
    width, height = A4

    label_w = 70 * mm
    label_h = 35 * mm
    margin_x = 10 * mm
    margin_y = 10 * mm
    gap_x = 5 * mm
    gap_y = 5 * mm

    cols = int((width - 2 * margin_x + gap_x) // (label_w + gap_x))
    if cols < 1:
        cols = 1

    x = margin_x
    y = height - margin_y - label_h

    def draw_label(prod: Product, x0, y0):
        c.roundRect(x0, y0, label_w, label_h, 6, stroke=1, fill=0)

        name = (prod.name or "")[:26]
        sku = (getattr(prod, "sku", "") or "")[:22]
        price = f"${prod.sell_price}" if prod.sell_price is not None else ""

        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0 + 4 * mm, y0 + label_h - 7 * mm, name)

        c.setFont("Helvetica", 8)
        if sku:
            c.drawString(x0 + 4 * mm, y0 + label_h - 12 * mm, f"SKU: {sku}")
        c.drawString(x0 + 4 * mm, y0 + label_h - 17 * mm, f"Price: {price}")

        value = (prod.code or "").strip()
        if value:
            bc = code128.Code128(value, barHeight=12 * mm, humanReadable=True)
            bc.drawOn(c, x0 + 4 * mm, y0 + 4 * mm)
        else:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(x0 + 4 * mm, y0 + 8 * mm, "No barcode (code)")

    items = list(queryset.order_by("name"))
    for i, prod in enumerate(items):
        if y < margin_y:
            c.showPage()
            y = height - margin_y - label_h
            x = margin_x

        draw_label(prod, x, y)

        if (i + 1) % cols == 0:
            x = margin_x
            y -= (label_h + gap_y)
        else:
            x += (label_w + gap_x)

    c.showPage()
    c.save()
    return resp


print_barcodes_pdf.short_description = "🖨️ Print Barcodes (PDF)"


# ==========================================================
# Product Admin
# ==========================================================
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "code", "sku", "sell_price",
        "weight_display", "supplier", "stock", "barcode_pdf_link"
    )
    search_fields = ("name", "code", "sku", "supplier__name")
    list_filter = ("category", "supplier")
    ordering = ("-id",)

    actions = ["action_print_barcodes_pdf"]

    # 🔒 LOCK STOCK SAAT EDIT
    def get_readonly_fields(self, request, obj=None):
        if obj:  # kalau edit existing product
            return ("stock",)
        return ()

    def weight_display(self, obj):
        return f"{obj.weight} {obj.unit.name if obj.unit else ''}"
    weight_display.short_description = "Weight"

    def barcode_pdf_link(self, obj):
        url = f"/admin/print-barcodes/?ids={obj.id}"
        return format_html(
            '<a class="button" href="{}" target="_blank">🖨️ Barcode</a>', url
        )
    barcode_pdf_link.short_description = "Barcode PDF"

    @admin.action(description="🖨️ Print Barcodes (PDF)")
    def action_print_barcodes_pdf(self, request, queryset):
        ids = ",".join(str(x) for x in queryset.values_list("id", flat=True))
        url = f"/admin/print-barcodes/?ids={ids}"
        return HttpResponseRedirect(url)



# ==========================================================
# Order Admin
# ==========================================================
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "id",
        "customer_name",
        "order_type",
        "total",
        "payment_method",
        "created_at_formatted",
        "served_by_display",
        "is_paid",
        "receipt_link",
    )
    search_fields = ("invoice_number", "customer__name", "id")
    list_filter = ("payment_method", "is_paid", "default_order_type")
    ordering = ("-created_at",)
    exclude = ("served_by",)

    def customer_name(self, obj):
        return obj.customer.name if obj.customer else "Walk In Customer"
    customer_name.short_description = "Name"

    def order_type(self, obj):
        try:
            return obj.get_default_order_type_display()
        except Exception:
            return "Take-Out"
    order_type.short_description = "Type"

    def created_at_formatted(self, obj):
        return obj.created_at.strftime("%I:%M %p, %d %B, %Y")
    created_at_formatted.short_description = "Time"

    def served_by_display(self, obj):
        if not obj.served_by:
            return "-"
        full_name = getattr(obj.served_by, "full_name", None)
        return full_name or obj.served_by.username
    served_by_display.short_description = "Served By"

    def receipt_link(self, obj):
        url = reverse("order_receipt_pdf", args=[obj.id])
        return format_html('<a class="button" href="{}" target="_blank">🧾</a>', url)
    receipt_link.short_description = "Receipt"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Admin site only accessible by superuser anyway,
        # but keep logic safe if staff changes later
        if request.user.is_superuser:
            return qs
        return qs.filter(served_by=request.user)

    def save_model(self, request, obj, form, change):
        if not obj.served_by_id:
            obj.served_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ["title", "active"]


# ==========================================================
# Inventory Admins
# ==========================================================
@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "old_stock", "new_stock", "reason", "adjusted_at", "adjusted_by")
    search_fields = ("product__name", "product__code", "product__sku")
    list_filter = ("reason",)
    ordering = ("-adjusted_at", "-id")


class InventoryCountItemInline(admin.TabularInline):
    model = InventoryCountItem
    extra = 0


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "counted_at", "counted_by")
    inlines = [InventoryCountItemInline]
    ordering = ("-counted_at", "-id")


class ProductReturnItemInline(admin.TabularInline):
    model = ProductReturnItem
    extra = 0


@admin.register(ProductReturn)
class ProductReturnAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "customer", "returned_at", "returned_by")
    inlines = [ProductReturnItemInline]
    ordering = ("-returned_at", "-id")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "movement_type", "quantity_delta", "before_stock", "after_stock", "created_at", "created_by")
    search_fields = ("product__name", "product__code", "product__sku")
    list_filter = ("movement_type",)
    ordering = ("-created_at", "-id")


# ==========================================================
# Simple registrations
# ==========================================================
admin.site.register(Customer)
admin.site.register(Supplier)
admin.site.register(Category)
admin.site.register(Unit)
admin.site.register(Expense)
admin.site.register(Shop)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Clean Jazzmin UI:
    - ONLY dropdown role
    - No groups / user_permissions
    - No manual is_staff / is_superuser (auto-synced in model.save)
    """

    fieldsets = (
        ("Login Info", {"fields": ("username", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "email")}),
        ("Role Settings", {"fields": ("role",)}),
        ("System Info", {"fields": ("is_active", "last_login", "date_joined")}),
    )

    add_fieldsets = (
        ("Create User", {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2", "role", "is_active"),
        }),
    )

    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username", "email")
    ordering = ("username",)

    # Remove permissions UI completely
    filter_horizontal = ()
    readonly_fields = ("last_login", "date_joined")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Prevent accidental self-demotion (optional but safe)
        if obj and obj.pk == request.user.pk:
            if "role" in form.base_fields:
                form.base_fields["role"].disabled = True

        return form

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("id", "shop", "cashier", "status", "opened_at", "closed_at", "opening_cash", "closing_cash", "expected_cash", "cash_difference")
    list_filter = ("status", "shop", "opened_at")
    search_fields = ("cashier__username", "cashier__email")

@admin.register(TokenProxy)
class TokenProxyAdmin(admin.ModelAdmin):
    list_display = ("key", "user", "created")
    search_fields = ("key", "user__username", "user__email")
    ordering = ("-created",)