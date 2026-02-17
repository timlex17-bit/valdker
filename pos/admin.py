from django.urls import reverse
from django.utils.html import format_html
from .models import Banner
from .models import TokenProxy
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

# Registu models iha ne.
from .models import (
    Customer, Supplier, Category, Unit,
    Product, Order, OrderItem, Expense, Shop
)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'code', 'sell_price', 'weight_display', 'supplier', 'stock')
    search_fields = ('name', 'code', 'supplier__name')
    list_filter = ('category', 'supplier')
    ordering = ('-id',)

    def weight_display(self, obj):
        return f"{obj.weight} {obj.unit.name if obj.unit else ''}"
    weight_display.short_description = 'Weight'


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer_name', 'invoice_id', 'order_type', 'total', 'payment_method', 'created_at_formatted', 'served_by', 'is_paid', 'receipt_link')
    search_fields = ('customer__name', 'id')
    list_filter = ('payment_method', 'is_paid', 'default_order_type')
    ordering = ('-created_at',)
    exclude = ('served_by',)

    def customer_name(self, obj):
        return obj.customer.name if obj.customer else "Walk In Customer"
    customer_name.short_description = 'Name'

    def invoice_id(self, obj):
        return f"INV{obj.id:015d}"
    invoice_id.short_description = 'Invoice ID'

    # ✅ FIX: tampilkan type dari Order.default_order_type
    def order_type(self, obj):
        try:
            # show label (Dine-In / Take-Out / Delivery)
            return obj.get_default_order_type_display()
        except Exception:
            return "Take-Out"
    order_type.short_description = 'Type'

    def created_at_formatted(self, obj):
        return obj.created_at.strftime("%I:%M %p, %d %B, %Y")
    created_at_formatted.short_description = 'Time'

    # ✅ DIUBAH: tampilkan full_name jika ada, fallback ke username
    def served_by(self, obj):
        if not obj.served_by:
            return "-"
        full_name = getattr(obj.served_by, "full_name", None)
        if full_name:
            return full_name
        return obj.served_by.username
    served_by.short_description = 'Served By'

    def receipt_link(self, obj):
        url = reverse('order_receipt_pdf', args=[obj.id])
        return format_html(f'<a class="button" href="{url}" target="_blank">🧾</a>')
    receipt_link.short_description = 'Receipt'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.role in ['admin', 'manager']:
            return qs
        return qs.filter(served_by=request.user)

    def save_model(self, request, obj, form, change):
        if not obj.served_by_id:
            obj.served_by = request.user
        super().save_model(request, obj, form, change)

    # ✅ TAMBAH: pastikan served_by tetap terset walau edit lewat inline/formset
    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance.save()
        formset.save_m2m()

        # pastikan object utama juga tetap punya served_by
        if hasattr(form, "instance") and getattr(form.instance, "served_by_id", None) is None:
            form.instance.served_by = request.user
            form.instance.save()


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'active']


admin.site.register(Customer)
admin.site.register(Supplier)
admin.site.register(Category)
admin.site.register(Unit)
admin.site.register(Expense)
admin.site.register(Shop)


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'is_active', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role',)}),
    )


admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(TokenProxy)
class TokenProxyAdmin(admin.ModelAdmin):
    list_display = ("key", "user", "created")
    search_fields = ("key", "user__username", "user__email")
    ordering = ("-created",)
