from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import F
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import AbstractUser
from cloudinary.models import CloudinaryField


# ========== CUSTOM USER ==========
class CustomUser(AbstractUser):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_CASHIER = "cashier"

    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_CASHIER, "Cashier"),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_CASHIER, db_index=True)

    @property
    def role_label(self):
        # compatibility for templates/context processors
        if self.is_superuser:
            return self.ROLE_ADMIN
        return self.role or self.ROLE_CASHIER

    def save(self, *args, **kwargs):
        """
        HARD POLICY:
        - ADMIN => is_superuser=True and is_staff=True
        - MANAGER/CASHIER => is_superuser=False and is_staff=False
        """
        r = (self.role or self.ROLE_CASHIER).lower().strip()

        if r == self.ROLE_ADMIN:
            self.is_superuser = True
            self.is_staff = True
        else:
            self.is_superuser = False
            self.is_staff = False

        super().save(*args, **kwargs)

    def get_feature_permissions(self):
        """
        Central Feature Permission Mapping
        Android & API will use this.
        """

        ROLE_PERMISSIONS = {
            self.Role.ADMIN: [
                "pos.view_reports",
                "pos.view_income",
                "pos.manage_products",
                "pos.manage_users",
                "pos.manage_expenses",
                "pos.create_orders",
                "pos.refunds",
                "pos.stock_adjust",
                "pos.export_data",
                "pos.manage_settings",
                "pos.manage_suppliers",
                "pos.manage_customers",
            ],
            self.Role.MANAGER: [
                "pos.view_reports",
                "pos.view_income",
                "pos.manage_products",
                "pos.manage_expenses",
                "pos.create_orders",
                "pos.refunds",
                "pos.stock_adjust",
                "pos.export_data",
                "pos.manage_suppliers",
                "pos.manage_customers",
            ],
            self.Role.CASHIER: [
                "pos.create_orders",
                "pos.refunds",
                "pos.manage_customers",
            ],
        }

        return ROLE_PERMISSIONS.get(self.role, [])

    def has_feature(self, feature_code: str) -> bool:
        return feature_code in self.get_feature_permissions()


# ========== CUSTOMER ==========
class Customer(models.Model):
    name = models.CharField(max_length=100)
    cell = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)

    # ✅ NEW: loyalty points
    points = models.IntegerField(default=0)

    def __str__(self):
        return self.name


# ========== SUPPLIER ==========
class Supplier(models.Model):
    name = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100)
    cell = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name


# ========== CATEGORY ==========
class Category(models.Model):
    name = models.CharField(max_length=100)
    icon = CloudinaryField("category_icon", blank=True, null=True)

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


# ========== PRODUCT ==========
class Product(models.Model):
    name = models.CharField(max_length=100)

    # ✅ code = BARCODE (keep for backward compatibility with your current apps)
    code = models.CharField(max_length=50, unique=True)

    # ✅ NEW: SKU (optional but recommended)
    sku = models.CharField(max_length=50, blank=True, default="", db_index=True)

    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    description = models.TextField(blank=True)
    stock = models.IntegerField(default=0)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    weight = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True)

    image = CloudinaryField("product_image", blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


# ========== ORDER ==========
class Order(models.Model):
    class OrderType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        DINE_IN = "DINE_IN", "Dine-In"
        TAKE_OUT = "TAKE_OUT", "Take-Out"
        DELIVERY = "DELIVERY", "Delivery"

    invoice_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Auto generated invoice number. Example: INV000000000123"
    )

    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    payment_method = models.CharField(max_length=50)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    is_paid = models.BooleanField(default=True)

    default_order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.TAKE_OUT,
        db_index=True
    )
    table_number = models.CharField(max_length=20, blank=True, default="")
    delivery_address = models.TextField(blank=True, default="")
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    )

    def generate_invoice_number(self) -> str:
        # Format professional: INV + 12 digit
        return f"INV{self.pk:012d}"

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)

        # After we have pk, generate invoice once
        if (creating or not self.invoice_number) and self.pk:
            inv = self.generate_invoice_number()
            if self.invoice_number != inv:
                Order.objects.filter(pk=self.pk).update(invoice_number=inv)
                self.invoice_number = inv

    def __str__(self):
        # tampilkan invoice biar enak dibaca di admin
        return self.invoice_number or f"Order #{self.id}"


class OrderItem(models.Model):
    class OrderType(models.TextChoices):
        DINE_IN = "DINE_IN", "Dine-In"
        TAKE_OUT = "TAKE_OUT", "Take-Out"
        DELIVERY = "DELIVERY", "Delivery"

    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    weight_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True)

    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.TAKE_OUT,
        db_index=True
    )


# ========== EXPENSE ==========
class Expense(models.Model):
    name = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    time = models.TimeField()

    def __str__(self):
        return self.name


# ========== SHOP ==========
class Shop(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    logo = CloudinaryField("shop_logo", blank=True, null=True)
    all_category_icon = CloudinaryField("all_category_icon", blank=True, null=True)


# ========== BANNER ==========
class Banner(models.Model):
    title = models.CharField(max_length=100)
    image = CloudinaryField("banner_image")
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


# ==========================================================
# INVENTORY LEDGER (Inventory History)
# ==========================================================
class StockMovement(models.Model):
    class Type(models.TextChoices):
        SALE = "SALE", "Sale"
        SALE_RETURN = "SALE_RETURN", "Sale Return"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        COUNT = "COUNT", "Inventory Count"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)

    # Positive = IN, Negative = OUT
    quantity_delta = models.IntegerField()

    before_stock = models.IntegerField()
    after_stock = models.IntegerField()

    note = models.CharField(max_length=255, blank=True, default="")
    ref_model = models.CharField(max_length=50, blank=True, default="")
    ref_id = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.product.name} {self.movement_type} {self.quantity_delta}"


# ==========================================================
# STOCK ADJUSTMENTS
# ==========================================================
class StockAdjustment(models.Model):
    class Reason(models.TextChoices):
        DAMAGE = "DAMAGE", "Damage"
        LOST = "LOST", "Lost"
        FOUND = "FOUND", "Found"
        CORRECTION = "CORRECTION", "Correction"

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    old_stock = models.IntegerField()
    new_stock = models.IntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.CORRECTION)
    note = models.CharField(max_length=255, blank=True, default="")
    adjusted_at = models.DateTimeField(default=timezone.now, db_index=True)
    adjusted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("-adjusted_at", "-id")

    def __str__(self):
        return f"Adj {self.product.name} {self.old_stock}->{self.new_stock}"


# ==========================================================
# INVENTORY COUNTS (Stock Opname)
# ==========================================================
class InventoryCount(models.Model):
    title = models.CharField(max_length=120, default="Stock Count")
    note = models.CharField(max_length=255, blank=True, default="")
    counted_at = models.DateTimeField(default=timezone.now, db_index=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("-counted_at", "-id")

    def __str__(self):
        return f"Count #{self.id} - {self.title}"


class InventoryCountItem(models.Model):
    count = models.ForeignKey(InventoryCount, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    system_stock = models.IntegerField()
    counted_stock = models.IntegerField()

    @property
    def difference(self):
        return self.counted_stock - self.system_stock


# ==========================================================
# PRODUCT RETURN (Sale Return)
# ==========================================================
class ProductReturn(models.Model):
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True, default="")
    returned_at = models.DateTimeField(default=timezone.now, db_index=True)
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ("-returned_at", "-id")

    def __str__(self):
        return f"Return #{self.id}"


class ProductReturnItem(models.Model):
    product_return = models.ForeignKey(ProductReturn, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)


class TokenProxy(Token):
    class Meta:
        proxy = True
        app_label = "pos"
        verbose_name = "Token"
        verbose_name_plural = "Tokens"
