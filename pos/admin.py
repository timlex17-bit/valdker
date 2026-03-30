from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.db import transaction
from django.http import HttpResponseRedirect, HttpResponse
from django.utils.http import urlencode
from django.urls import reverse
from django.utils.html import format_html
from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128

from pos.models_shift import Shift
from pos.forms import ShopAdminForm
from pos.services import ShopProvisionService

from .models import (
    Banner, PlatformUser, ShopStaffUser, TokenProxy,
    Customer, Supplier, Category, Unit,
    Product, Order, Expense, Shop,
    StockAdjustment, InventoryCount,
    ProductReturn, StockMovement,
    PaymentMethod, BankAccount, SalePayment, BankLedger,
    Purchase, PurchaseItem
)


# ==========================================================
# TOKEN ADMIN
# ==========================================================
@admin.register(TokenProxy)
class TokenProxyAdmin(admin.ModelAdmin):

    list_display = ("key","user","created")

    search_fields = (
        "key",
        "user__username",
        "user__email"
    )

    ordering = ("-created",)

    def has_module_permission(self,request):
        return request.user.is_superuser

    def has_view_permission(self,request,obj=None):
        return request.user.is_superuser


# ==========================================================
# PURCHASE ADMIN
# ==========================================================

class PurchaseItemInline(admin.TabularInline):

    model = PurchaseItem

    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "shop",
        "invoice_id",
        "supplier",
        "purchase_date",
        "created_at",
        "created_by"
    )

    list_filter = (
        "shop",
        "purchase_date",
        "supplier"
    )

    search_fields = (
        "invoice_id",
        "supplier__name"
    )

    inlines = [PurchaseItemInline]


# ==========================================================
# PDF BARCODE
# ==========================================================

def _barcode_pdf_response(filename="barcodes.pdf"):

    resp = HttpResponse(content_type="application/pdf")

    resp["Content-Disposition"] = f'inline; filename="{filename}"'

    return resp


def print_barcodes_pdf(modeladmin,request,queryset):

    resp = _barcode_pdf_response("product_barcodes.pdf")

    c = canvas.Canvas(resp,pagesize=A4)

    width,height = A4

    label_w = 70*mm
    label_h = 35*mm

    margin_x = 10*mm
    margin_y = 10*mm

    gap_x = 5*mm
    gap_y = 5*mm

    cols = int((width-2*margin_x+gap_x)//(label_w+gap_x))

    if cols < 1:
        cols = 1

    x = margin_x
    y = height-margin_y-label_h

    def draw_label(prod,x0,y0):

        c.roundRect(x0,y0,label_w,label_h,6)

        name = (prod.name or "")[:26]

        sku = (getattr(prod,"sku","") or "")[:22]

        price = f"${prod.sell_price}"

        c.setFont("Helvetica-Bold",9)

        c.drawString(x0+4*mm,y0+label_h-7*mm,name)

        c.setFont("Helvetica",8)

        if sku:
            c.drawString(x0+4*mm,y0+label_h-12*mm,f"SKU: {sku}")

        c.drawString(x0+4*mm,y0+label_h-17*mm,f"Price: {price}")

        value = (prod.code or "").strip()

        if value:

            bc = code128.Code128(
                value,
                barHeight=12*mm,
                humanReadable=True
            )

            bc.drawOn(c,x0+4*mm,y0+4*mm)

    items=list(queryset.order_by("name"))

    for i,prod in enumerate(items):

        if y<margin_y:

            c.showPage()

            y=height-margin_y-label_h

            x=margin_x

        draw_label(prod,x,y)

        if (i+1)%cols==0:

            x=margin_x

            y-=(label_h+gap_y)

        else:

            x+=(label_w+gap_x)

    c.showPage()

    c.save()

    return resp


print_barcodes_pdf.short_description="Print Barcodes"


# ==========================================================
# PRODUCT ADMIN
# ==========================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name",
        "code",
        "sku",
        "sell_price",
        "supplier",
        "stock",
        "barcode_pdf_link"

    )

    search_fields=(

        "name",
        "code",
        "sku",
        "supplier__name"

    )

    list_filter=(

        "shop",
        "category",
        "supplier"

    )

    ordering=("-id",)

    actions=["action_print_barcodes_pdf"]

    def get_readonly_fields(self,request,obj=None):

        if obj:
            return("stock",)

        return()

    def barcode_pdf_link(self,obj):

        url=f"/admin/print-barcodes/?ids={obj.id}"

        return format_html(
            '<a class="button" href="{}">Barcode</a>',
            url
        )

    def action_print_barcodes_pdf(self,request,queryset):

        ids=",".join(
            str(x)
            for x in queryset.values_list("id",flat=True)
        )

        url=f"/admin/print-barcodes/?ids={ids}"

        return HttpResponseRedirect(url)


# ==========================================================
# BANK ACCOUNT
# ==========================================================

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name",
        "bank_name",
        "account_number",
        "account_holder",
        "account_type",
        "opening_balance",
        "current_balance",
        "is_active"

    )

    list_filter=(

        "shop",
        "account_type",
        "is_active",
        "bank_name"

    )

    search_fields=(

        "name",
        "bank_name",
        "account_number"

    )

    ordering=("bank_name","name")

    list_editable=("is_active",)

    autocomplete_fields=("shop",)


# ==========================================================
# ORDER ADMIN
# ==========================================================

class SalePaymentInline(admin.TabularInline):

    model=SalePayment

    extra=0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    inlines=[SalePaymentInline]

    list_display=(

        "invoice_number",
        "shop",
        "customer_name",
        "total",
        "created_at",
        "served_by_display"

    )

    list_filter=(

        "shop",
        "payment_method",
        "is_paid"

    )

    ordering=("-created_at",)

    def customer_name(self,obj):

        if obj.customer:
            return obj.customer.name

        return "Walk In"

    def served_by_display(self,obj):

        if obj.served_by:
            return obj.served_by.username

        return "-"

    def save_model(self,request,obj,form,change):

        if not obj.served_by_id:

            obj.served_by=request.user

        if not obj.shop_id:

            obj.shop=request.user.shop

        super().save_model(request,obj,form,change)


# ==========================================================
# INVENTORY
# ==========================================================

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "product",
        "movement_type",
        "quantity_delta",
        "before_stock",
        "after_stock",
        "created_at"

    )

    list_filter=(

        "shop",
        "movement_type"

    )


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "product",
        "old_stock",
        "new_stock",
        "reason",
        "adjusted_at"

    )

    list_filter=(

        "shop",
        "reason"

    )


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "title",
        "counted_at"

    )

    list_filter=(

        "shop",
        "status"

    )


@admin.register(ProductReturn)
class ProductReturnAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "order",
        "customer",
        "returned_at"

    )

    list_filter=(

        "shop",

    )


# ==========================================================
# SIMPLE ADMINS
# ==========================================================

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name",
        "cell",
        "email"

    )

    list_filter=("shop",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name",
        "cell"

    )

    list_filter=("shop",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name"

    )

    list_filter=("shop",)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name"

    )

    list_filter=("shop",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "name",
        "amount",
        "date"

    )

    list_filter=("shop",)
    

class ShopStaffInlineForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(
        label="Password",
        help_text="Password tidak ditampilkan. Gunakan halaman user terpisah jika ingin reset password."
    )

    class Meta:
        model = ShopStaffUser
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "is_active",
            "password",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [
            ("manager", "Manager"),
            ("cashier", "Cashier"),
        ]

    def clean_role(self):
        role = (self.cleaned_data.get("role") or "").strip().lower()
        allowed = ["manager", "cashier"]
        if role not in allowed:
            raise forms.ValidationError("Role harus manager atau cashier.")
        return role
    

class ShopStaffInline(admin.TabularInline):
    model = ShopStaffUser
    form = ShopStaffInlineForm
    extra = 0
    fk_name = "shop"

    fields = (
        "username",
        "first_name",
        "last_name",
        "email",
        "role",
        "is_active",
    )

    verbose_name = "Shop Staff"
    verbose_name_plural = "Shop Staff"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(shop__isnull=False, is_superuser=False).exclude(role="owner")
        
        
# ==========================================================
# SHOP ADMIN
# ==========================================================

@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    form = ShopAdminForm
    inlines = [ShopStaffInline]

    list_display = (
        "id",
        "name",
        "code",
        "slug",
        "business_type",
        "owner_display",
        "staff_count",
        "add_staff_link",
        "subdomain_display",
        "custom_domain_display",
        "is_active",
    )
    search_fields = ("name", "code", "slug", "email", "phone")
    list_filter = ("business_type", "is_active")
    readonly_fields = ("owner", "created_at")

    def owner_display(self, obj):
        if getattr(obj, "owner", None):
            return obj.owner.username
        return "-"
    owner_display.short_description = "Owner"

    def staff_count(self, obj):
        return obj.users.exclude(role="owner").count()

    def add_staff_link(self, obj):
        url = reverse("admin:pos_shopstaffuser_add")
        query = urlencode({"shop": obj.id})
        return format_html('<a class="button" href="{}?{}">Add Staff</a>', url, query)
    add_staff_link.short_description = "Add Staff"

    def subdomain_display(self, obj):
        return getattr(obj, "subdomain", "") or "-"
    subdomain_display.short_description = "Subdomain"

    def custom_domain_display(self, obj):
        return getattr(obj, "custom_domain", "") or "-"
    custom_domain_display.short_description = "Custom domain"

    def _shop_model_fields(self):
        return {f.name for f in self.model._meta.get_fields()}

    def _existing_fields(self, *field_names):
        existing = self._shop_model_fields()
        return tuple(field for field in field_names if field in existing)

    def get_fieldsets(self, request, obj=None):
        fieldsets = []

        basic_info = self._existing_fields(
            "name",
            "code",
            "slug",
            "business_type",
            "is_active"
        )
        if basic_info:
            fieldsets.append(("Basic Info", {"fields": basic_info}))

        contact = self._existing_fields("phone", "email", "address")
        if contact:
            fieldsets.append(("Contact", {"fields": contact}))

        owner_fields = []
        if "owner" in self._shop_model_fields():
            owner_fields.append("owner")

        owner_fields += [
            "owner_full_name",
            "owner_username",
            "owner_email",
            "owner_password1",
            "owner_password2",
            "provision_defaults",
        ]

        fieldsets.append(("Primary Owner", {"fields": tuple(owner_fields)}))

        domain_fields = self._existing_fields(
            "subdomain",
            "custom_domain",
            "frontend_url",
            "backend_url",
        )
        if domain_fields:
            fieldsets.append(("Domain / URL Config", {"fields": domain_fields}))

        notes_fields = self._existing_fields("notes")
        if notes_fields:
            fieldsets.append(("Notes", {"fields": notes_fields}))

        system_fields = self._existing_fields("created_at")
        if system_fields:
            fieldsets.append(("System Info", {"fields": system_fields}))

        return fieldsets

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None

        super().save_model(request, obj, form, change)

        provision_defaults = form.cleaned_data.get("provision_defaults", True)

        if is_new and provision_defaults:
            result = ShopProvisionService.provision(
                shop=obj,
                owner_username=form.cleaned_data["owner_username"],
                owner_email=form.cleaned_data.get("owner_email", ""),
                owner_password=form.cleaned_data["owner_password1"],
                owner_full_name=form.cleaned_data.get("owner_full_name", ""),
                created_by=request.user,
            )

            owner = result["owner"]
            self.message_user(
                request,
                f"Shop '{obj.name}' berhasil dibuat dan diprovision. Owner: {owner.username}",
                level=messages.SUCCESS,
            )

        elif change:
            password1 = form.cleaned_data.get("owner_password1")
            password2 = form.cleaned_data.get("owner_password2")

            if password1 and password2 and password1 == password2 and getattr(obj, "owner", None):
                obj.owner.set_password(password1)
                obj.owner.save(update_fields=["password"])
                self.message_user(
                    request,
                    f"Password owner untuk shop '{obj.name}' berhasil diperbarui.",
                    level=messages.SUCCESS,
                )


# ==========================================================
# USER ADMIN
# ==========================================================

@admin.register(PlatformUser)
class PlatformUserAdmin(UserAdmin):
    fieldsets = (
        ("Login", {"fields": ("username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "email")}),
        ("Platform Access", {"fields": ("is_active", "is_superuser")}),
        ("Permissions", {"fields": ("groups", "user_permissions")}),
        ("System", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        ("Create Platform User", {
            "classes": ("wide",),
            "fields": (
                "username",
                "email",
                "password1",
                "password2",
                "is_active",
                "is_superuser",
            ),
        }),
    )

    list_display = (
        "username",
        "email",
        "is_superuser",
        "is_active",
    )

    list_filter = (
        "is_superuser",
        "is_active",
    )

    search_fields = (
        "username",
        "email",
    )

    ordering = ("username",)
    readonly_fields = ("last_login", "date_joined")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(is_superuser=True)

    def save_model(self, request, obj, form, change):
        obj.shop = None
        obj.is_superuser = True
        super().save_model(request, obj, form, change)
    

@admin.register(ShopStaffUser)
class ShopStaffUserAdmin(UserAdmin):

    fieldsets = (
        ("Login", {"fields": ("username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "email")}),
        ("Shop Role", {"fields": ("shop", "role", "is_active")}),
        ("System", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        ("Create Shop Staff", {
            "classes": ("wide",),
            "fields": (
                "username",
                "email",
                "password1",
                "password2",
                "shop",
                "role",
                "is_active",
            ),
        }),
    )

    list_display = (
        "username",
        "shop",
        "email",
        "role",
        "is_active",
    )

    list_filter = (
        "shop",
        "role",
        "is_active",
    )

    search_fields = (
        "username",
        "email",
        "shop__name",
        "shop__code",
    )

    ordering = ("shop", "username")

    readonly_fields = (
        "last_login",
        "date_joined"
    )

    def has_module_permission(self, request):
        # HILANGKAN DARI SIDEBAR
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(shop__isnull=False, is_superuser=False)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)

        shop_id = request.GET.get("shop")

        if shop_id:
            initial["shop"] = shop_id

        return initial

    def save_model(self, request, obj, form, change):

        if not obj.shop_id:
            raise ValueError("Shop wajib diisi.")

        obj.is_superuser = False
        obj.is_staff = False

        super().save_model(request, obj, form, change)
        

# ==========================================================
# BANNER
# ==========================================================

@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):

    list_display=("title","active")


# ==========================================================
# SHIFT
# ==========================================================

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):

    list_display=(

        "id",
        "shop",
        "cashier",
        "status",
        "opened_at"

    )