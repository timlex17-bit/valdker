from decimal import Decimal
from django.db import models, transaction
from django.db.models import Q, F
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser
from rest_framework.authtoken.models import Token
from cloudinary.models import CloudinaryField
from .models_backup import BackupSetting, BackupHistory, RestoreHistory
from .models_import import ImportJob, ImportRowError
from .models_shift import Shift, ShiftStatus


# ==========================================================
# BASE MIXIN
# ==========================================================
class CleanSaveMixin:
    """
    Production-safe save:
    - run model validation before save
    """
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# ========== CUSTOM USER ==========
class CustomUser(CleanSaveMixin, AbstractUser):
    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_CASHIER = "cashier"

    ROLE_CHOICES = (
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_CASHIER, "Cashier"),
    )

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CASHIER,
        db_index=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["shop", "role"]),
        ]

    @property
    def role_label(self):
        if self.is_superuser:
            return "platform_admin"
        return self.role or self.ROLE_CASHIER

    @property
    def is_platform_admin(self):
        return bool(self.is_superuser)

    @property
    def is_owner(self):
        return (self.role or "").lower().strip() == self.ROLE_OWNER

    @property
    def is_manager(self):
        return (self.role or "").lower().strip() == self.ROLE_MANAGER

    @property
    def is_cashier(self):
        return (self.role or "").lower().strip() == self.ROLE_CASHIER

    @property
    def is_shop_owner(self):
        return bool(self.shop_id and self.is_owner)

    @property
    def is_shop_manager(self):
        return bool(self.shop_id and self.is_manager)

    @property
    def is_shop_cashier(self):
        return bool(self.shop_id and self.is_cashier)

    @property
    def is_shop_admin(self):
        return bool(self.shop_id and (self.is_owner or self.is_manager))

    def clean(self):
        self.role = (self.role or self.ROLE_CASHIER).lower().strip()

        valid_roles = {self.ROLE_OWNER, self.ROLE_MANAGER, self.ROLE_CASHIER}
        if self.role not in valid_roles:
            raise ValidationError({"role": "Invalid role."})

        if self.is_superuser:
            self.shop = None
            self.is_staff = True
        else:
            self.is_staff = False
            if not self.shop_id:
                raise ValidationError({"shop": "Non-platform user must belong to a shop."})

    def get_feature_permissions(self):
        ROLE_PERMISSIONS = {
            self.ROLE_OWNER: [
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
                "pos.manage_purchases",
                "pos.manage_payment_methods",
                "pos.manage_bank_accounts",
                "pos.manage_inventory_counts",
                "pos.view_stock_movements",
            ],
            self.ROLE_MANAGER: [
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
                "pos.manage_purchases",
                "pos.manage_inventory_counts",
                "pos.view_stock_movements",
            ],
            self.ROLE_CASHIER: [
                "pos.create_orders",
                "pos.refunds",
                "pos.manage_customers",
                "pos.reprint_receipt",
                "pos.shift_open_close",
            ],
        }
        return ROLE_PERMISSIONS.get(self.role, [])

    def has_feature(self, feature_code: str) -> bool:
        return self.is_superuser or feature_code in self.get_feature_permissions()

    def __str__(self):
        return self.username


class PlatformUser(CustomUser):
    class Meta:
        proxy = True
        verbose_name = "Platform User"
        verbose_name_plural = "Platform Users"


class ShopStaffUser(CustomUser):
    class Meta:
        proxy = True
        verbose_name = "Shop Staff"
        verbose_name_plural = "Shop Staff"


# ========== SHOP ==========
class Shop(CleanSaveMixin, models.Model):
    class BusinessType(models.TextChoices):
        RESTAURANT = "restaurant", "Restaurant"
        RETAIL = "retail", "Retail"
        WORKSHOP = "workshop", "Workshop"

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    business_type = models.CharField(
        max_length=20,
        choices=BusinessType.choices,
        default=BusinessType.RETAIL,
        db_index=True
    )

    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_shops"
    )

    subdomain = models.CharField(max_length=100, blank=True, null=True, unique=True)
    custom_domain = models.CharField(max_length=255, blank=True, null=True, unique=True)

    frontend_url = models.URLField(blank=True, null=True)
    backend_url = models.URLField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")

    logo = CloudinaryField("shop_logo", blank=True, null=True)
    all_category_icon = CloudinaryField("all_category_icon", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Shop"
        verbose_name_plural = "Shops"
        indexes = [
            models.Index(fields=["is_active", "name"]),
            models.Index(fields=["code"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["business_type"]),
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()
        self.slug = (self.slug or "").strip().lower()
        self.business_type = (self.business_type or self.BusinessType.RETAIL).strip().lower()
        self.address = (self.address or "").strip()
        self.phone = (self.phone or "").strip()
        self.notes = (self.notes or "").strip()
        self.subdomain = (self.subdomain or "").strip().lower() or None
        self.custom_domain = (self.custom_domain or "").strip().lower() or None

        valid_business_types = {
            self.BusinessType.RESTAURANT,
            self.BusinessType.RETAIL,
            self.BusinessType.WORKSHOP,
        }
        if self.business_type not in valid_business_types:
            raise ValidationError({"business_type": "Invalid business type."})

        if not self.name:
            raise ValidationError({"name": "Shop name is required."})

        if not self.code:
            raise ValidationError({"code": "Shop code is required."})

        if not self.slug and self.name:
            self.slug = slugify(self.name)

        if not self.slug:
            raise ValidationError({"slug": "Slug is required."})

        if not self.address:
            raise ValidationError({"address": "Address is required."})

        if not self.phone:
            raise ValidationError({"phone": "Phone is required."})

        if self.owner_id and self.owner:
            if not self.owner.is_superuser:
                if self.owner.role != CustomUser.ROLE_OWNER:
                    raise ValidationError({
                        "owner": "Selected user must have owner role."
                    })

                if self.owner.shop_id and self.owner.shop_id != self.pk:
                    raise ValidationError({
                        "owner": "Owner user already belongs to another shop."
                    })

    def __str__(self):
        return f"{self.name} ({self.code})"
    
    
class ShopFeature(CleanSaveMixin, models.Model):
    shop = models.OneToOneField(
        "Shop",
        on_delete=models.CASCADE,
        related_name="features"
    )

    enable_dine_in = models.BooleanField(default=False)
    enable_takeaway = models.BooleanField(default=False)
    enable_delivery = models.BooleanField(default=False)
    enable_table_number = models.BooleanField(default=False)

    enable_barcode_scan = models.BooleanField(default=True)
    enable_customer_points = models.BooleanField(default=True)
    enable_split_payment = models.BooleanField(default=True)

    enable_service_fee = models.BooleanField(default=False)
    enable_mechanic = models.BooleanField(default=False)
    enable_vehicle_info = models.BooleanField(default=False)

    show_product_images_in_pos = models.BooleanField(default=True)
    use_grid_pos_layout = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop Feature"
        verbose_name_plural = "Shop Features"

    def clean(self):
        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

    def __str__(self):
        return f"Features - {self.shop.name}"    


# ========== CUSTOMER ==========
class Customer(CleanSaveMixin, models.Model):
    shop = models.ForeignKey("Shop", on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=100)
    cell = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, default="")
    points = models.IntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["shop", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "cell"],
                condition=~Q(cell=""),
                name="unique_customer_cell_per_shop_when_present"
            )
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.cell = (self.cell or "").strip()
        self.address = (self.address or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Customer name is required."})
        if self.points < 0:
            raise ValidationError({"points": "Points cannot be negative."})

    def __str__(self):
        return self.name


# ========== SUPPLIER ==========
class Supplier(CleanSaveMixin, models.Model):
    shop = models.ForeignKey("Shop", on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100, blank=True, default="")
    cell = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["shop", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["shop", "name"], name="unique_supplier_name_per_shop")
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.contact_person = (self.contact_person or "").strip()
        self.cell = (self.cell or "").strip()
        self.address = (self.address or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Supplier name is required."})

    def __str__(self):
        return self.name


# ========== CATEGORY ==========
class Category(CleanSaveMixin, models.Model):
    shop = models.ForeignKey("Shop", on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=100)
    icon = CloudinaryField("category_icon", blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["shop", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["shop", "name"], name="unique_category_per_shop")
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Category name is required."})

    def __str__(self):
        return self.name


class Unit(CleanSaveMixin, models.Model):
    shop = models.ForeignKey("Shop", on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=50)

    class Meta:
        indexes = [
            models.Index(fields=["shop", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["shop", "name"], name="unique_unit_per_shop")
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Unit name is required."})

    def __str__(self):
        return self.name


# ========== PRODUCT ==========
class Product(CleanSaveMixin, models.Model):
    class ItemType(models.TextChoices):
        PRODUCT = "product", "Product"
        MENU = "menu", "Menu"
        SERVICE = "service", "Service"
        SPAREPART = "sparepart", "Sparepart"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="products"
    )

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50)
    sku = models.CharField(max_length=50, blank=True, null=True)

    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        default=ItemType.PRODUCT,
        db_index=True
    )

    category = models.ForeignKey(
        "Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    description = models.TextField(blank=True, default="")
    stock = models.IntegerField(default=0)
    track_stock = models.BooleanField(default=True)

    buy_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sell_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    weight = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    unit = models.ForeignKey(
        "Unit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    supplier = models.ForeignKey(
        "Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products"
    )

    image = CloudinaryField("product_image", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")
        indexes = [
            models.Index(fields=["shop", "name"]),
            models.Index(fields=["shop", "code"]),
            models.Index(fields=["shop", "sku"]),
            models.Index(fields=["shop", "is_active"]),
            models.Index(fields=["shop", "item_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "code"],
                name="unique_product_code_per_shop"
            ),
            models.UniqueConstraint(
                fields=["shop", "sku"],
                condition=Q(sku__isnull=False) & ~Q(sku=""),
                name="unique_product_sku_per_shop_when_present"
            ),
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip()
        self.sku = (self.sku or "").strip() or None
        self.description = (self.description or "").strip()
        self.item_type = (self.item_type or self.ItemType.PRODUCT).strip().lower()

        valid_item_types = {
            self.ItemType.PRODUCT,
            self.ItemType.MENU,
            self.ItemType.SERVICE,
            self.ItemType.SPAREPART,
        }
        if self.item_type not in valid_item_types:
            raise ValidationError({"item_type": "Invalid item type."})

        if self.item_type == self.ItemType.SERVICE:
            self.track_stock = False

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Product name is required."})
        if not self.code:
            raise ValidationError({"code": "Product code is required."})
        if self.stock < 0:
            raise ValidationError({"stock": "Stock cannot be negative."})
        if self.buy_price < 0:
            raise ValidationError({"buy_price": "Buy price cannot be negative."})
        if self.sell_price < 0:
            raise ValidationError({"sell_price": "Sell price cannot be negative."})
        if self.weight < 0:
            raise ValidationError({"weight": "Weight cannot be negative."})

        if self.category_id and self.category and self.category.shop_id != self.shop_id:
            raise ValidationError({"category": "Category must belong to the same shop."})

        if self.unit_id and self.unit and self.unit.shop_id != self.shop_id:
            raise ValidationError({"unit": "Unit must belong to the same shop."})

        if self.supplier_id and self.supplier and self.supplier.shop_id != self.shop_id:
            raise ValidationError({"supplier": "Supplier must belong to the same shop."})

    def __str__(self):
        return f"{self.name} ({self.code})"


# ==========================================================
# PURCHASES (Stock In from Supplier)
# ==========================================================
class Purchase(CleanSaveMixin, models.Model):
    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="purchases"
    )

    supplier = models.ForeignKey(
        "Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases"
    )

    invoice_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    purchase_date = models.DateField(default=timezone.localdate, db_index=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_purchases"
    )

    class Meta:
        ordering = ("-purchase_date", "-id")
        indexes = [
            models.Index(fields=["shop", "purchase_date"]),
            models.Index(fields=["shop", "created_at"]),
            models.Index(fields=["shop", "invoice_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "invoice_id"],
                condition=~Q(invoice_id=""),
                name="unique_purchase_invoice_per_shop_when_present"
            ),
        ]

    def clean(self):
        self.invoice_id = (self.invoice_id or "").strip()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if not self.purchase_date:
            raise ValidationError({"purchase_date": "Purchase date is required."})

        if self.supplier_id and self.supplier and self.supplier.shop_id != self.shop_id:
            raise ValidationError({"supplier": "Supplier must belong to the same shop."})

        if self.created_by_id and self.created_by and not self.created_by.is_superuser:
            if self.created_by.shop_id != self.shop_id:
                raise ValidationError({"created_by": "User must belong to the same shop."})

    def __str__(self):
        sup = self.supplier.name if self.supplier else "No Supplier"
        inv = self.invoice_id or f"Purchase #{self.id}"
        return f"{inv} - {sup}"


class PurchaseItem(CleanSaveMixin, models.Model):
    purchase = models.ForeignKey(
        "Purchase",
        related_name="items",
        on_delete=models.CASCADE
    )

    product = models.ForeignKey(
        "Product",
        on_delete=models.PROTECT,
        related_name="purchase_items"
    )

    quantity = models.PositiveIntegerField(default=1)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expired_date = models.DateField(null=True, blank=True)
    batch_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(fields=["purchase", "product"]),
            models.Index(fields=["product", "expired_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase", "product", "cost_price", "expired_date", "batch_code"],
                name="unique_purchase_item_batch_line"
            ),
        ]

    def clean(self):
        self.batch_code = (self.batch_code or "").strip()

        if not self.purchase_id:
            raise ValidationError({"purchase": "Purchase is required."})

        if not self.product_id:
            raise ValidationError({"product": "Product is required."})

        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than 0."})

        if self.cost_price < 0:
            raise ValidationError({"cost_price": "Cost price cannot be negative."})

        if self.purchase_id and self.product_id:
            if self.purchase.shop_id != self.product.shop_id:
                raise ValidationError({
                    "product": "Product harus berasal dari shop yang sama dengan purchase."
                })

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"


# ========== ORDER ==========
class Order(CleanSaveMixin, models.Model):
    class OrderType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        DINE_IN = "DINE_IN", "Dine-In"
        TAKE_OUT = "TAKE_OUT", "Take-Out"
        DELIVERY = "DELIVERY", "Delivery"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="orders"
    )

    invoice_number = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        blank=True,
        default=""
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    payment_method = models.CharField(max_length=50, blank=True, default="")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True, default="")
    is_paid = models.BooleanField(default=True)

    default_order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.GENERAL,
        db_index=True
    )

    table_number = models.CharField(max_length=20, blank=True, default="")
    delivery_address = models.TextField(blank=True, default="")
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["shop", "created_at"]),
            models.Index(fields=["shop", "is_paid"]),
            models.Index(fields=["shop", "default_order_type"]),
        ]

    def generate_invoice_number(self) -> str:
        return f"INV{self.pk:012d}"

    def clean(self):
        self.payment_method = (self.payment_method or "").strip()
        self.notes = (self.notes or "").strip()
        self.table_number = (self.table_number or "").strip()
        self.delivery_address = (self.delivery_address or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.subtotal < 0:
            raise ValidationError({"subtotal": "Subtotal cannot be negative."})
        if self.discount < 0:
            raise ValidationError({"discount": "Discount cannot be negative."})
        if self.tax < 0:
            raise ValidationError({"tax": "Tax cannot be negative."})
        if self.delivery_fee < 0:
            raise ValidationError({"delivery_fee": "Delivery fee cannot be negative."})
        if self.total < 0:
            raise ValidationError({"total": "Total cannot be negative."})

        if self.customer_id and self.customer and self.customer.shop_id != self.shop_id:
            raise ValidationError({"customer": "Customer harus berasal dari shop yang sama."})

        if self.served_by_id and self.served_by and not self.served_by.is_superuser:
            if self.served_by.shop_id != self.shop_id:
                raise ValidationError({"served_by": "User harus berasal dari shop yang sama."})

        if self.shop_id and self.shop:
            if self.shop.business_type in {Shop.BusinessType.RETAIL, Shop.BusinessType.WORKSHOP}:
                if self.default_order_type != self.OrderType.GENERAL:
                    raise ValidationError({
                        "default_order_type": "Only GENERAL order type is allowed for non-restaurant shops."
                    })

                if self.table_number:
                    raise ValidationError({
                        "table_number": "Table number is only allowed for restaurant shops."
                    })

                if self.delivery_address:
                    raise ValidationError({
                        "delivery_address": "Delivery address is only allowed for restaurant shops."
                    })

                if self.delivery_fee != Decimal("0"):
                    raise ValidationError({
                        "delivery_fee": "Delivery fee is only allowed for restaurant shops."
                    })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        self.full_clean()
        super().save(*args, **kwargs)

        if (is_new or not self.invoice_number) and self.pk:
            inv = self.generate_invoice_number()
            if self.invoice_number != inv:
                self.invoice_number = inv
                super().save(update_fields=["invoice_number"])

    def __str__(self):
        return self.invoice_number or f"Order #{self.id}"


class OrderItem(CleanSaveMixin, models.Model):
    class OrderType(models.TextChoices):
        GENERAL = "GENERAL", "General"
        DINE_IN = "DINE_IN", "Dine-In"
        TAKE_OUT = "TAKE_OUT", "Take-Out"
        DELIVERY = "DELIVERY", "Delivery"

    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    weight_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)

    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.GENERAL,
        db_index=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["order", "product"]),
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than 0."})
        if self.price < 0:
            raise ValidationError({"price": "Price cannot be negative."})

        if self.order_id and self.product_id:
            if self.order.shop_id != self.product.shop_id:
                raise ValidationError({
                    "product": "Product harus berasal dari shop yang sama dengan order."
                })

        if self.weight_unit_id and self.order_id:
            if self.weight_unit.shop_id != self.order.shop_id:
                raise ValidationError({
                    "weight_unit": "Unit harus berasal dari shop yang sama dengan order."
                })

        if self.order_id and self.order and self.order.shop_id:
            shop = self.order.shop
            if shop.business_type in {Shop.BusinessType.RETAIL, Shop.BusinessType.WORKSHOP}:
                if self.order_type != self.OrderType.GENERAL:
                    raise ValidationError({
                        "order_type": "Only GENERAL item order type is allowed for non-restaurant shops."
                    })


# ========== EXPENSE ==========
class Expense(CleanSaveMixin, models.Model):
    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="expenses"
    )

    name = models.CharField(max_length=100)
    note = models.TextField(blank=True, default="")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    time = models.TimeField()

    class Meta:
        indexes = [
            models.Index(fields=["shop", "date"]),
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Expense name is required."})
        if self.amount < 0:
            raise ValidationError({"amount": "Amount cannot be negative."})

    def __str__(self):
        return self.name


# ==========================================================
# PAYMENT METHODS
# ==========================================================
class PaymentMethod(CleanSaveMixin, models.Model):
    class PaymentType(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK = "BANK", "Bank Transfer"
        QRIS = "QRIS", "QRIS"
        CARD = "CARD", "Card"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="payment_methods"
    )

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30, db_index=True)
    payment_type = models.CharField(
        max_length=20,
        choices=PaymentType.choices,
        default=PaymentType.CASH,
        db_index=True
    )
    requires_bank_account = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=["shop", "payment_type"]),
            models.Index(fields=["shop", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "code"],
                name="unique_payment_method_code_per_shop"
            ),
            models.UniqueConstraint(
                fields=["shop", "name"],
                name="unique_payment_method_name_per_shop"
            ),
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.code = (self.code or "").strip().upper()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Name is required."})
        if not self.code:
            raise ValidationError({"code": "Code is required."})

    def __str__(self):
        return f"{self.shop.name} - {self.name}"


# ==========================================================
# BANK ACCOUNTS
# ==========================================================
class BankAccount(CleanSaveMixin, models.Model):
    class AccountType(models.TextChoices):
        BANK = "BANK", "Bank"
        EWALLET = "EWALLET", "E-Wallet"
        QRIS = "QRIS", "QRIS"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="bank_accounts"
    )

    name = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50, blank=True, default="")
    account_holder = models.CharField(max_length=100, blank=True, default="")
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.BANK,
        db_index=True
    )

    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("bank_name", "name")
        indexes = [
            models.Index(fields=["shop", "is_active"]),
            models.Index(fields=["shop", "bank_name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "bank_name", "name"],
                name="unique_bank_account_name_per_shop"
            )
        ]

    def clean(self):
        self.name = (self.name or "").strip()
        self.bank_name = (self.bank_name or "").strip()
        self.account_number = (self.account_number or "").strip()
        self.account_holder = (self.account_holder or "").strip()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.name:
            raise ValidationError({"name": "Name is required."})
        if not self.bank_name:
            raise ValidationError({"bank_name": "Bank name is required."})
        if self.opening_balance < 0:
            raise ValidationError({"opening_balance": "Opening balance cannot be negative."})
        if self.current_balance < 0:
            raise ValidationError({"current_balance": "Current balance cannot be negative."})

    def __str__(self):
        return f"{self.bank_name} - {self.name}"


# ==========================================================
# ORDER PAYMENTS (supports split payment)
# ==========================================================
class SalePayment(CleanSaveMixin, models.Model):
    order = models.ForeignKey(
        Order,
        related_name="payments",
        on_delete=models.CASCADE
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.PROTECT,
        related_name="sale_payments"
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="sale_payments",
        null=True,
        blank=True
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference_number = models.CharField(max_length=100, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    paid_at = models.DateTimeField(default=timezone.now, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_sale_payments"
    )

    class Meta:
        ordering = ("paid_at", "id")
        indexes = [
            models.Index(fields=["order", "paid_at"]),
        ]

    def clean(self):
        self.reference_number = (self.reference_number or "").strip()
        self.note = (self.note or "").strip()

        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Amount harus lebih besar dari 0."})

        if self.payment_method_id and self.order_id:
            if self.payment_method.shop_id != self.order.shop_id:
                raise ValidationError({
                    "payment_method": "Payment method harus berasal dari shop yang sama dengan order."
                })

        if self.payment_method_id:
            if self.payment_method.requires_bank_account and not self.bank_account:
                raise ValidationError({
                    "bank_account": "Bank account wajib dipilih untuk metode pembayaran ini."
                })

            if not self.payment_method.requires_bank_account and self.bank_account:
                if self.payment_method.payment_type == PaymentMethod.PaymentType.CASH:
                    raise ValidationError({
                        "bank_account": "Metode cash tidak boleh memakai bank account."
                    })

        if self.bank_account_id and self.order_id:
            if self.bank_account.shop_id != self.order.shop_id:
                raise ValidationError({
                    "bank_account": "Bank account harus berasal dari shop yang sama dengan order."
                })

        if self.created_by_id and self.order_id and not self.created_by.is_superuser:
            if self.created_by.shop_id != self.order.shop_id:
                raise ValidationError({
                    "created_by": "User harus berasal dari shop yang sama dengan order."
                })

    def __str__(self):
        return f"{self.order.invoice_number} - {self.payment_method.name} - {self.amount}"


# ==========================================================
# BANK LEDGER (bank mutation history)
# ==========================================================
class BankLedger(CleanSaveMixin, models.Model):
    class TransactionType(models.TextChoices):
        SALE_IN = "SALE_IN", "Sale Income"
        DEPOSIT = "DEPOSIT", "Cash Deposit"
        WITHDRAW = "WITHDRAW", "Withdraw"
        TRANSFER_IN = "TRANSFER_IN", "Transfer In"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer Out"
        REFUND_OUT = "REFUND_OUT", "Refund Out"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Direction(models.TextChoices):
        IN = "IN", "In"
        OUT = "OUT", "Out"

    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="ledgers"
    )

    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
        db_index=True
    )
    direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        db_index=True
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    reference_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_ledgers"
    )
    reference_payment = models.ForeignKey(
        SalePayment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_ledgers"
    )

    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_bank_ledgers"
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["bank_account", "created_at"]),
            models.Index(fields=["bank_account", "transaction_type"]),
        ]

    def clean(self):
        self.description = (self.description or "").strip()

        if not self.bank_account_id:
            raise ValidationError({"bank_account": "Bank account is required."})

        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Amount harus lebih besar dari 0."})

        if self.balance_before < 0:
            raise ValidationError({"balance_before": "Balance before cannot be negative."})

        if self.balance_after < 0:
            raise ValidationError({"balance_after": "Balance after cannot be negative."})

        shop_id = self.bank_account.shop_id if self.bank_account_id else None

        if self.reference_order_id and self.reference_order.shop_id != shop_id:
            raise ValidationError({
                "reference_order": "Order harus berasal dari shop yang sama dengan bank account."
            })

        if self.reference_payment_id and self.reference_payment.order.shop_id != shop_id:
            raise ValidationError({
                "reference_payment": "Payment harus berasal dari shop yang sama dengan bank account."
            })

        # Tambahan penting:
        # Jika dua-duanya diisi, payment harus milik order yang sama
        if self.reference_order_id and self.reference_payment_id:
            if self.reference_payment.order_id != self.reference_order_id:
                raise ValidationError({
                    "reference_payment": "Payment must belong to the same reference order."
                })

        if self.created_by_id and self.created_by and not self.created_by.is_superuser:
            if self.created_by.shop_id != shop_id:
                raise ValidationError({
                    "created_by": "User harus berasal dari shop yang sama dengan bank account."
                })

    def __str__(self):
        return f"{self.bank_account} - {self.transaction_type} - {self.amount}"


# ========== BANNER ==========
class Banner(CleanSaveMixin, models.Model):
    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="banners",
    )
    title = models.CharField(max_length=100)
    image = CloudinaryField("banner_image")
    active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["shop", "active"]),
        ]

    def clean(self):
        self.title = (self.title or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if not self.title:
            raise ValidationError({"title": "Title is required."})

    def __str__(self):
        return self.title


# ==========================================================
# INVENTORY LEDGER (Inventory History)
# ==========================================================
class StockMovement(CleanSaveMixin, models.Model):
    class Type(models.TextChoices):
        SALE = "SALE", "Sale"
        SALE_RETURN = "SALE_RETURN", "Sale Return"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"
        COUNT = "COUNT", "Inventory Count"
        PURCHASE = "PURCHASE", "Purchase"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="stock_movements"
    )

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)

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
        indexes = [
            models.Index(fields=["shop", "created_at"]),
            models.Index(fields=["shop", "movement_type"]),
        ]

    def clean(self):
        self.note = (self.note or "").strip()
        self.ref_model = (self.ref_model or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.product_id and self.product and self.product.shop_id != self.shop_id:
            raise ValidationError({
                "product": "Product harus berasal dari shop yang sama dengan stock movement."
            })

        if self.created_by_id and self.created_by and not self.created_by.is_superuser:
            if self.created_by.shop_id != self.shop_id:
                raise ValidationError({
                    "created_by": "User harus berasal dari shop yang sama dengan stock movement."
                })

    def __str__(self):
        return f"{self.product.name} {self.movement_type} {self.quantity_delta}"


# ==========================================================
# STOCK ADJUSTMENTS
# ==========================================================
class StockAdjustment(CleanSaveMixin, models.Model):
    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="stock_adjustments"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    old_stock = models.IntegerField()
    new_stock = models.IntegerField()
    reason = models.CharField(max_length=100)
    note = models.TextField(blank=True, default="")
    adjusted_at = models.DateTimeField(auto_now_add=True)
    adjusted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    class Meta:
        indexes = [
            models.Index(fields=["shop", "adjusted_at"]),
        ]

    def clean(self):
        self.reason = (self.reason or "").strip()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.reason:
            raise ValidationError({"reason": "Reason is required."})
        if self.old_stock < 0:
            raise ValidationError({"old_stock": "Old stock cannot be negative."})
        if self.new_stock < 0:
            raise ValidationError({"new_stock": "New stock cannot be negative."})

        if self.product_id and self.product and self.product.shop_id != self.shop_id:
            raise ValidationError({
                "product": "Product harus berasal dari shop yang sama dengan stock adjustment."
            })

        if self.adjusted_by_id and self.adjusted_by and not self.adjusted_by.is_superuser:
            if self.adjusted_by.shop_id != self.shop_id:
                raise ValidationError({
                    "adjusted_by": "User harus berasal dari shop yang sama dengan stock adjustment."
                })

    def __str__(self):
        return f"{self.product.name} | {self.old_stock} -> {self.new_stock}"


# ==========================================================
# INVENTORY COUNTS (Stock Opname)
# ==========================================================
class InventoryCount(CleanSaveMixin, models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_COMPLETED = "COMPLETED"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_COMPLETED, "Completed"),
    ]

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="inventory_counts"
    )

    title = models.CharField(max_length=200)
    note = models.TextField(blank=True, default="")

    counted_at = models.DateTimeField(default=timezone.now, db_index=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_counts"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-counted_at", "-id")
        indexes = [
            models.Index(fields=["shop", "status"]),
            models.Index(fields=["shop", "counted_at"]),
        ]

    def clean(self):
        self.title = (self.title or "").strip()
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})
        if not self.title:
            raise ValidationError({"title": "Title is required."})

        if self.counted_by_id and self.counted_by and not self.counted_by.is_superuser:
            if self.counted_by.shop_id != self.shop_id:
                raise ValidationError({"counted_by": "User harus berasal dari shop yang sama."})

    def __str__(self):
        return self.title


class InventoryCountItem(CleanSaveMixin, models.Model):
    inventory = models.ForeignKey(
        InventoryCount,
        related_name="items",
        on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_count_items"
    )

    system_stock = models.IntegerField()
    counted_stock = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inventory", "product"],
                name="unique_product_per_inventory_count"
            )
        ]

    @property
    def difference(self):
        return self.counted_stock - self.system_stock

    def clean(self):
        if self.system_stock < 0:
            raise ValidationError({
                "system_stock": "System stock cannot be negative."
            })

        if self.counted_stock < 0:
            raise ValidationError({
                "counted_stock": "Counted stock cannot be negative."
            })

        if self.inventory_id and self.product_id:
            if self.inventory.shop_id != self.product.shop_id:
                raise ValidationError({
                    "product": "Product harus berasal dari shop yang sama dengan inventory count."
                })

# ==========================================================
# PRODUCT RETURN (Sale Return)
# ==========================================================
class ProductReturn(CleanSaveMixin, models.Model):
    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="product_returns"
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_returns"
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_returns"
    )

    note = models.CharField(max_length=255, blank=True, default="")
    returned_at = models.DateTimeField(default=timezone.now, db_index=True)

    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_returns"
    )

    class Meta:
        ordering = ("-returned_at", "-id")
        indexes = [
            models.Index(fields=["shop", "returned_at"]),
        ]

    def clean(self):
        self.note = (self.note or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.order_id and self.order and self.order.shop_id != self.shop_id:
            raise ValidationError({"order": "Order harus berasal dari shop yang sama."})

        if self.customer_id and self.customer and self.customer.shop_id != self.shop_id:
            raise ValidationError({"customer": "Customer harus berasal dari shop yang sama."})

        if self.returned_by_id and self.returned_by and not self.returned_by.is_superuser:
            if self.returned_by.shop_id != self.shop_id:
                raise ValidationError({"returned_by": "User harus berasal dari shop yang sama."})

    def __str__(self):
        return f"Return #{self.id}"


class ProductReturnItem(CleanSaveMixin, models.Model):
    product_return = models.ForeignKey(
        ProductReturn,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="product_return_items"
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product_return", "product"],
                name="unique_product_per_return"
            )
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than 0."})
        if self.unit_price < 0:
            raise ValidationError({"unit_price": "Unit price cannot be negative."})

        if self.product_return_id and self.product_id:
            if self.product_return.shop_id != self.product.shop_id:
                raise ValidationError({"product": "Product harus berasal dari shop yang sama dengan product return."})


class TokenProxy(Token):
    class Meta:
        proxy = True
        app_label = "pos"
        verbose_name = "Token"
        verbose_name_plural = "Tokens"