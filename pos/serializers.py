from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from .models import (
    Customer, Supplier, Product, Category, Unit, Banner,
    Order, OrderItem, Shop, ShopFeature, Expense,
    StockAdjustment, InventoryCount, InventoryCountItem,
    ProductReturn, ProductReturnItem, StockMovement,
    PaymentMethod, BankAccount, SalePayment, BankLedger,
    Warehouse, WarehouseStock, sync_product_total_stock,
    StockTransfer, StockTransferItem,
)

User = get_user_model()


# ==========================================================
# Helper functions
# ==========================================================
def _force_https(url: str | None) -> str | None:
    if not url:
        return url
    return url.replace("http://", "https://")


def _abs_or_raw(request, url: str | None) -> str | None:
    if not url:
        return None
    if request and url.startswith("/"):
        return request.build_absolute_uri(url)
    return url

def _normalize_media_url(request, field_file):
    if not field_file:
        return None
    try:
        url = field_file.url
        if request and url.startswith("/"):
            return request.build_absolute_uri(url)
        return url
    except Exception:
        return None

def _request_user(context):
    request = context.get("request")
    return getattr(request, "user", None)


def _request_shop(context):
    user = _request_user(context)
    return getattr(user, "shop", None)


def require_authenticated_user(context):
    user = _request_user(context)
    if not user or not user.is_authenticated:
        raise serializers.ValidationError("Authentication required.")
    return user


def require_tenant_shop(context):
    shop = _request_shop(context)
    if not shop:
        raise serializers.ValidationError("Tenant shop context is missing.")
    return shop


def tenant_qs(model, context, **filters):
    """
    Safe tenant queryset helper.
    Returns none() if tenant shop is missing.
    """
    shop = _request_shop(context)
    if not shop:
        return model.objects.none()
    return model.objects.filter(shop=shop, **filters)


def tenant_active_qs(model, context, **filters):
    """
    Safe tenant queryset helper for models with is_active.
    """
    shop = _request_shop(context)
    if not shop:
        return model.objects.none()
    return model.objects.filter(shop=shop, is_active=True, **filters)


def model_has_field(model, field_name: str) -> bool:
    return any(getattr(field, "name", None) == field_name for field in model._meta.get_fields())


def ensure_instance_belongs_to_shop(instance, context):
    shop = require_tenant_shop(context)
    instance_shop_id = getattr(instance, "shop_id", None)
    if instance_shop_id is not None and instance_shop_id != shop.id:
        raise serializers.ValidationError("This object does not belong to your shop.")
    return shop


def inject_shop_if_supported(model, validated_data, shop):
    if model_has_field(model, "shop") and "shop" not in validated_data:
        validated_data["shop"] = shop
    return validated_data


def clean_str(value):
    return (value or "").strip()


# ==========================================================
# Customer / Supplier / Category / Unit
# ==========================================================
class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "cell", "email", "address", "points"]

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        name = clean_str(attrs.get("name"))
        cell = clean_str(attrs.get("cell"))
        email = clean_str(attrs.get("email"))
        address = clean_str(attrs.get("address"))

        if not name:
            raise serializers.ValidationError({"name": "Customer name is required."})

        if not cell:
            raise serializers.ValidationError({"cell": "Phone number is required."})

        attrs["name"] = name
        attrs["cell"] = cell
        attrs["email"] = email
        attrs["address"] = address

        qs = Customer.objects.filter(shop=shop, cell=cell)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({"cell": "Customer dengan nomor ini sudah ada."})

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Customer, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "cell", "email", "address"]

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        name = clean_str(attrs.get("name"))
        contact_person = clean_str(attrs.get("contact_person"))
        cell = clean_str(attrs.get("cell"))
        email = clean_str(attrs.get("email"))
        address = clean_str(attrs.get("address"))

        if not name:
            raise serializers.ValidationError({"name": "Supplier name is required."})

        attrs["name"] = name
        attrs["contact_person"] = contact_person
        attrs["cell"] = cell
        attrs["email"] = email
        attrs["address"] = address

        qs = Supplier.objects.filter(shop=shop, name__iexact=name)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({"name": "Supplier dengan nama ini sudah ada."})

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Supplier, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


class CategorySerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "icon", "icon_url"]
        extra_kwargs = {
            "icon": {"required": False, "allow_null": True},
        }

    def validate_name(self, value):
        shop = require_tenant_shop(self.context)

        value = clean_str(value)
        if not value:
            raise serializers.ValidationError("Category name is required.")

        qs = Category.objects.filter(shop=shop, name__iexact=value)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("Category dengan nama ini sudah ada.")

        return value

    def get_icon_url(self, obj):
        request = self.context.get("request")
        return _normalize_media_url(request, obj.icon) or ""

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Category, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "name"]

    def validate_name(self, value):
        shop = require_tenant_shop(self.context)

        value = clean_str(value)
        if not value:
            raise serializers.ValidationError("Unit name is required.")

        qs = Unit.objects.filter(shop=shop, name__iexact=value)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError("Unit dengan nama ini sudah ada.")

        return value

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Unit, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)
    
    
# ==========================================================
# Warehouse
# ==========================================================
class WarehouseSerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source="shop.id", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "name",
            "code",
            "location",
            "is_active",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        name = clean_str(attrs.get("name") or getattr(self.instance, "name", ""))
        code = clean_str(attrs.get("code") or getattr(self.instance, "code", "")).upper()
        location = clean_str(attrs.get("location") or getattr(self.instance, "location", ""))

        if not name:
            raise serializers.ValidationError({"name": "Warehouse name is required."})

        if not code:
            raise serializers.ValidationError({"code": "Warehouse code is required."})

        attrs["name"] = name
        attrs["code"] = code
        attrs["location"] = location

        qs_name = Warehouse.objects.filter(shop=shop, name__iexact=name)
        qs_code = Warehouse.objects.filter(shop=shop, code__iexact=code)

        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs_name = qs_name.exclude(pk=self.instance.pk)
            qs_code = qs_code.exclude(pk=self.instance.pk)

        if qs_name.exists():
            raise serializers.ValidationError({
                "name": "Warehouse dengan nama ini sudah ada di shop Anda."
            })

        if qs_code.exists():
            raise serializers.ValidationError({
                "code": "Warehouse code sudah ada di shop Anda."
            })

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Warehouse, validated_data, shop)

        with transaction.atomic():
            is_default = validated_data.get("is_default", False)

            # Jika warehouse pertama di shop, otomatis default
            if not Warehouse.objects.filter(shop=shop).exists():
                validated_data["is_default"] = True
                is_default = True

            if is_default:
                Warehouse.objects.filter(shop=shop, is_default=True).update(is_default=False)

            obj = Warehouse.objects.create(**validated_data)
            return obj

    def update(self, instance, validated_data):
        shop = ensure_instance_belongs_to_shop(instance, self.context)

        with transaction.atomic():
            is_default = validated_data.get("is_default", instance.is_default)

            if is_default:
                Warehouse.objects.filter(shop=shop, is_default=True).exclude(
                    pk=instance.pk
                ).update(is_default=False)

            instance = super().update(instance, validated_data)

            # Pastikan shop selalu punya minimal 1 default warehouse
            if not Warehouse.objects.filter(shop=shop, is_default=True).exists():
                instance.is_default = True
                instance.save(update_fields=["is_default"])

            return instance    


# ==========================================================
# Warehouse Stock
# ==========================================================
class WarehouseStockSerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source="shop.id", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)

    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_track_stock = serializers.BooleanField(source="product.track_stock", read_only=True)

    is_low_stock = serializers.BooleanField(read_only=True)

    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())

    class Meta:
        model = WarehouseStock
        fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "warehouse",
            "warehouse_name",
            "warehouse_code",
            "product",
            "product_name",
            "product_code",
            "product_sku",
            "product_track_stock",
            "quantity",
            "min_stock",
            "is_low_stock",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "warehouse_name",
            "warehouse_code",
            "product_name",
            "product_code",
            "product_sku",
            "product_track_stock",
            "is_low_stock",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = tenant_qs(Warehouse, self.context)
        self.fields["product"].queryset = tenant_qs(Product, self.context, track_stock=True)

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        warehouse = attrs.get("warehouse", getattr(self.instance, "warehouse", None))
        product = attrs.get("product", getattr(self.instance, "product", None))
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 0))
        min_stock = attrs.get("min_stock", getattr(self.instance, "min_stock", 0))

        if warehouse is None:
            raise serializers.ValidationError({"warehouse": "Warehouse is required."})

        if product is None:
            raise serializers.ValidationError({"product": "Product is required."})

        if warehouse.shop_id != shop.id:
            raise serializers.ValidationError({"warehouse": "Warehouse does not belong to your shop."})

        if product.shop_id != shop.id:
            raise serializers.ValidationError({"product": "Product does not belong to your shop."})

        if not product.track_stock:
            raise serializers.ValidationError({"product": "This product does not use stock tracking."})

        if quantity is None or quantity < 0:
            raise serializers.ValidationError({"quantity": "Quantity must be 0 or greater."})

        if min_stock is None or min_stock < 0:
            raise serializers.ValidationError({"min_stock": "Minimum stock must be 0 or greater."})

        qs = WarehouseStock.objects.filter(shop=shop, warehouse=warehouse, product=product)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({
                "product": "Stock row for this product already exists in the selected warehouse."
            })

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(WarehouseStock, validated_data, shop)

        obj = WarehouseStock.objects.create(**validated_data)
        sync_product_total_stock(obj.product_id)
        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)

        instance = super().update(instance, validated_data)
        sync_product_total_stock(instance.product_id)
        return instance


# ==========================================================
# Stock Transfer
# ==========================================================
class StockTransferItemSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockTransferItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_code",
            "product_sku",
            "quantity",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "product_code",
            "product_sku",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = tenant_qs(Product, self.context, track_stock=True)

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)
        product = attrs.get("product")
        quantity = attrs.get("quantity")

        if product is None:
            raise serializers.ValidationError({"product": "Product is required."})

        if product.shop_id != shop.id:
            raise serializers.ValidationError({"product": "Product does not belong to your shop."})

        if not product.track_stock:
            raise serializers.ValidationError({"product": "This product does not use stock tracking."})

        if quantity is None or quantity <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than 0."})

        return attrs


class StockTransferSerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source="shop.id", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    from_warehouse_name = serializers.CharField(source="from_warehouse.name", read_only=True)
    from_warehouse_code = serializers.CharField(source="from_warehouse.code", read_only=True)

    to_warehouse_name = serializers.CharField(source="to_warehouse.name", read_only=True)
    to_warehouse_code = serializers.CharField(source="to_warehouse.code", read_only=True)

    created_by_name = serializers.SerializerMethodField()
    completed_by_name = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()

    from_warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none())
    to_warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none())

    items = StockTransferItemSerializer(many=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "reference_no",
            "from_warehouse",
            "from_warehouse_name",
            "from_warehouse_code",
            "to_warehouse",
            "to_warehouse_name",
            "to_warehouse_code",
            "note",
            "status",
            "created_by",
            "created_by_name",
            "completed_by",
            "completed_by_name",
            "completed_at",
            "cancelled_by",
            "cancelled_by_name",
            "cancelled_at",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "reference_no",
            "status",
            "created_by",
            "created_by_name",
            "completed_by",
            "completed_by_name",
            "completed_at",
            "cancelled_by",
            "cancelled_by_name",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["from_warehouse"].queryset = tenant_qs(Warehouse, self.context, is_active=True)
        self.fields["to_warehouse"].queryset = tenant_qs(Warehouse, self.context, is_active=True)

        if "items" in self.fields:
            child = self.fields["items"].child
            child.context.update(self.context)
            child.fields["product"].queryset = tenant_qs(Product, self.context, track_stock=True)

    def get_created_by_name(self, obj):
        if not obj.created_by:
            return ""
        return getattr(obj.created_by, "get_full_name", lambda: "")().strip() or getattr(obj.created_by, "username", "")

    def get_completed_by_name(self, obj):
        if not obj.completed_by:
            return ""
        return getattr(obj.completed_by, "get_full_name", lambda: "")().strip() or getattr(obj.completed_by, "username", "")

    def get_cancelled_by_name(self, obj):
        if not obj.cancelled_by:
            return ""
        return getattr(obj.cancelled_by, "get_full_name", lambda: "")().strip() or getattr(obj.cancelled_by, "username", "")

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        from_warehouse = attrs.get("from_warehouse", getattr(self.instance, "from_warehouse", None))
        to_warehouse = attrs.get("to_warehouse", getattr(self.instance, "to_warehouse", None))
        note = clean_str(attrs.get("note") or getattr(self.instance, "note", ""))
        items = attrs.get("items")

        attrs["note"] = note

        if from_warehouse is None:
            raise serializers.ValidationError({"from_warehouse": "Source warehouse is required."})

        if to_warehouse is None:
            raise serializers.ValidationError({"to_warehouse": "Destination warehouse is required."})

        if from_warehouse.shop_id != shop.id:
            raise serializers.ValidationError({"from_warehouse": "Source warehouse does not belong to your shop."})

        if to_warehouse.shop_id != shop.id:
            raise serializers.ValidationError({"to_warehouse": "Destination warehouse does not belong to your shop."})

        if from_warehouse.id == to_warehouse.id:
            raise serializers.ValidationError({
                "to_warehouse": "Destination warehouse must be different from source warehouse."
            })

        # Saat create wajib ada items
        if self.instance is None:
            if not items:
                raise serializers.ValidationError({"items": "Items cannot be empty."})

        if items is not None:
            if len(items) == 0:
                raise serializers.ValidationError({"items": "Items cannot be empty."})

            seen_products = set()
            for item in items:
                product = item["product"]
                if product.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' does not belong to your shop."
                    })

                if not product.track_stock:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' does not use stock tracking."
                    })

                if product.id in seen_products:
                    raise serializers.ValidationError({
                        "items": f"Duplicate product '{product.name}' in transfer items."
                    })
                seen_products.add(product.id)

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        user = require_authenticated_user(self.context)
        items_data = validated_data.pop("items", [])

        validated_data = inject_shop_if_supported(StockTransfer, validated_data, shop)
        validated_data["created_by"] = user
        validated_data["status"] = StockTransfer.STATUS_DRAFT

        obj = StockTransfer.objects.create(**validated_data)

        for item_data in items_data:
            StockTransferItem.objects.create(
                transfer=obj,
                product=item_data["product"],
                quantity=item_data["quantity"],
            )

        return obj

    @transaction.atomic
    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)

        if instance.status != StockTransfer.STATUS_DRAFT:
            raise serializers.ValidationError("Only draft transfer can be edited.")

        items_data = validated_data.pop("items", None)

        instance = super().update(instance, validated_data)

        if items_data is not None:
            instance.items.all().delete()

            for item_data in items_data:
                StockTransferItem.objects.create(
                    transfer=instance,
                    product=item_data["product"],
                    quantity=item_data["quantity"],
                )

        return instance


# ==========================================================
# Product
# ==========================================================
class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image = serializers.ImageField(use_url=True, required=False, allow_null=True)

    shop_id = serializers.IntegerField(source="shop.id", read_only=True)

    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.none(),
        source="category",
        write_only=True,
        required=False,
        allow_null=True,
    )

    supplier = SupplierSerializer(read_only=True)
    supplier_id = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.none(),
        source="supplier",
        write_only=True,
        required=False,
        allow_null=True,
    )

    unit = UnitSerializer(read_only=True)
    unit_id = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(),
        source="unit",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "code",
            "item_type",
            "track_stock",
            "description",
            "stock",
            "buy_price",
            "sell_price",
            "weight",
            "is_active",
            "image",
            "image_url",
            "shop_id",
            "category",
            "category_id",
            "supplier",
            "supplier_id",
            "unit",
            "unit_id",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["category_id"].queryset = tenant_qs(Category, self.context)
        self.fields["supplier_id"].queryset = tenant_qs(Supplier, self.context)
        self.fields["unit_id"].queryset = tenant_qs(Unit, self.context)

    def get_image_url(self, obj):
        request = self.context.get("request")
        return _normalize_media_url(request, obj.image)

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        name = clean_str(attrs.get("name") or getattr(self.instance, "name", ""))
        code = clean_str(attrs.get("code") or getattr(self.instance, "code", ""))
        sku = clean_str(attrs.get("sku") or getattr(self.instance, "sku", ""))
        description = clean_str(attrs.get("description") or getattr(self.instance, "description", ""))

        item_type = clean_str(
            attrs.get("item_type") or getattr(self.instance, "item_type", Product.ItemType.PRODUCT)
        ).lower()

        valid_item_types = {
            Product.ItemType.PRODUCT,
            Product.ItemType.MENU,
            Product.ItemType.SERVICE,
            Product.ItemType.SPAREPART,
        }
        if item_type not in valid_item_types:
            raise serializers.ValidationError({"item_type": "Invalid item type."})

        attrs["name"] = name
        attrs["code"] = code
        attrs["sku"] = sku or None
        attrs["description"] = description
        attrs["item_type"] = item_type

        if item_type == Product.ItemType.SERVICE:
            attrs["track_stock"] = False

        if not name:
            raise serializers.ValidationError({"name": "Product name is required."})

        if not code:
            raise serializers.ValidationError({"code": "Barcode/code is required."})

        qs = Product.objects.filter(shop=shop, code=code)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({"code": "Barcode/code sudah ada di toko ini."})

        if sku:
            qs = Product.objects.filter(shop=shop, sku=sku)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"sku": "SKU sudah ada di toko ini."})

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Product, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)

        if "stock" in validated_data:
            raise serializers.ValidationError({
                "stock": "Stock cannot be edited directly. Use Stock Adjustment."
            })

        item_type = clean_str(
            validated_data.get("item_type", getattr(instance, "item_type", Product.ItemType.PRODUCT))
        ).lower()
        if item_type == Product.ItemType.SERVICE:
            validated_data["track_stock"] = False

        return super().update(instance, validated_data)


# ==========================================================
# Order Item
# ==========================================================
class OrderItemSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    weight_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(),
        required=False,
        allow_null=True,
    )
    order_type = serializers.ChoiceField(
        choices=OrderItem.OrderType.choices,
        required=False
    )

    class Meta:
        model = OrderItem
        fields = ["product", "quantity", "price", "weight_unit", "order_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = tenant_qs(Product, self.context)
        self.fields["weight_unit"].queryset = tenant_qs(Unit, self.context)

    def validate_product(self, product):
        shop = require_tenant_shop(self.context)
        if product.shop_id != shop.id:
            raise serializers.ValidationError("Product does not belong to your shop.")
        return product

    def validate_weight_unit(self, weight_unit):
        if weight_unit is None:
            return weight_unit

        shop = require_tenant_shop(self.context)
        if weight_unit.shop_id != shop.id:
            raise serializers.ValidationError("Unit does not belong to your shop.")
        return weight_unit

    def validate(self, attrs):
        quantity = attrs.get("quantity") or 0
        price = attrs.get("price")

        if quantity <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than 0."})

        if price is None or price < 0:
            raise serializers.ValidationError({"price": "Price must be 0 or greater."})

        product = attrs.get("product")
        if product and not product.is_active:
            raise serializers.ValidationError({"product": "Product is not active."})

        return attrs


# ==========================================================
# Payment / Bank
# ==========================================================
class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "name",
            "code",
            "payment_type",
            "requires_bank_account",
            "is_active",
            "note",
        ]

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        name = clean_str(attrs.get("name") or getattr(self.instance, "name", ""))
        code = clean_str(attrs.get("code") or getattr(self.instance, "code", ""))
        note = clean_str(attrs.get("note"))

        if not name:
            raise serializers.ValidationError({"name": "Name is required."})
        if not code:
            raise serializers.ValidationError({"code": "Code is required."})

        attrs["name"] = name
        attrs["code"] = code
        attrs["note"] = note

        qs = PaymentMethod.objects.filter(shop=shop, code__iexact=code)
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({"code": "Payment method code sudah ada di shop ini."})

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(PaymentMethod, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


class BankAccountSerializer(serializers.ModelSerializer):
    shop_id = serializers.IntegerField(source="shop.id", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "name",
            "bank_name",
            "account_number",
            "account_holder",
            "account_type",
            "opening_balance",
            "current_balance",
            "is_active",
            "note",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "current_balance",
            "created_at",
        ]

    def validate(self, attrs):
        user = require_authenticated_user(self.context)
        shop = require_tenant_shop(self.context)

        if user.is_superuser:
            raise serializers.ValidationError(
                "Platform admin should not create tenant bank account from this endpoint."
            )

        name = clean_str(attrs.get("name") or getattr(self.instance, "name", ""))
        bank_name = clean_str(attrs.get("bank_name") or getattr(self.instance, "bank_name", ""))
        account_number = clean_str(attrs.get("account_number") or getattr(self.instance, "account_number", ""))
        account_holder = clean_str(attrs.get("account_holder") or getattr(self.instance, "account_holder", ""))
        note = clean_str(attrs.get("note"))

        if not name:
            raise serializers.ValidationError({"name": "Name is required."})

        if not bank_name:
            raise serializers.ValidationError({"bank_name": "Bank name is required."})

        attrs["name"] = name
        attrs["bank_name"] = bank_name
        attrs["account_number"] = account_number
        attrs["account_holder"] = account_holder
        attrs["note"] = note

        opening_balance = attrs.get("opening_balance", None)
        if opening_balance is not None and opening_balance < 0:
            raise serializers.ValidationError({
                "opening_balance": "Opening balance tidak boleh negatif."
            })

        qs = BankAccount.objects.filter(
            shop=shop,
            bank_name__iexact=bank_name,
            name__iexact=name,
        )
        if self.instance:
            ensure_instance_belongs_to_shop(self.instance, self.context)
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({
                "name": "Bank account dengan nama ini sudah ada untuk bank tersebut di shop ini."
            })

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        opening_balance = validated_data.get("opening_balance") or Decimal("0.00")
        validated_data = inject_shop_if_supported(BankAccount, validated_data, shop)
        validated_data["current_balance"] = opening_balance
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)

        validated_data.pop("current_balance", None)

        if "opening_balance" in validated_data:
            if instance.ledgers.exists():
                raise serializers.ValidationError({
                    "opening_balance": "Opening balance tidak boleh diubah karena rekening sudah memiliki ledger."
                })

            new_opening = validated_data.get("opening_balance") or Decimal("0.00")
            if new_opening < 0:
                raise serializers.ValidationError({
                    "opening_balance": "Opening balance tidak boleh negatif."
                })

            instance.current_balance = new_opening

        instance = super().update(instance, validated_data)

        if "opening_balance" in validated_data:
            instance.save(update_fields=["current_balance"])

        return instance


class SalePaymentSerializer(serializers.ModelSerializer):
    payment_method_name = serializers.CharField(source="payment_method.name", read_only=True)
    payment_type = serializers.CharField(source="payment_method.payment_type", read_only=True)
    bank_account_name = serializers.SerializerMethodField()

    class Meta:
        model = SalePayment
        fields = [
            "id",
            "order",
            "payment_method",
            "payment_method_name",
            "payment_type",
            "bank_account",
            "bank_account_name",
            "amount",
            "reference_number",
            "note",
            "paid_at",
            "created_by",
        ]
        read_only_fields = ["id", "paid_at", "created_by"]

    def get_bank_account_name(self, obj):
        if not obj.bank_account:
            return ""
        return f"{obj.bank_account.bank_name} - {obj.bank_account.name}"


class BankLedgerSerializer(serializers.ModelSerializer):
    bank_account_name = serializers.SerializerMethodField()
    reference_order_invoice = serializers.CharField(source="reference_order.invoice_number", read_only=True)
    shop_id = serializers.IntegerField(source="bank_account.shop.id", read_only=True)
    shop_name = serializers.CharField(source="bank_account.shop.name", read_only=True)
    shop_code = serializers.CharField(source="bank_account.shop.code", read_only=True)

    class Meta:
        model = BankLedger
        fields = [
            "id",
            "shop_id",
            "shop_name",
            "shop_code",
            "bank_account",
            "bank_account_name",
            "transaction_type",
            "direction",
            "amount",
            "balance_before",
            "balance_after",
            "reference_order",
            "reference_order_invoice",
            "reference_payment",
            "description",
            "created_at",
            "created_by",
        ]

    def get_bank_account_name(self, obj):
        if not obj.bank_account:
            return ""
        return f"{obj.bank_account.bank_name} - {obj.bank_account.name}"


class CheckoutPaymentInputSerializer(serializers.Serializer):
    payment_method_id = serializers.PrimaryKeyRelatedField(
        queryset=PaymentMethod.objects.none(),
        source="payment_method"
    )
    bank_account_id = serializers.PrimaryKeyRelatedField(
        queryset=BankAccount.objects.none(),
        source="bank_account",
        required=False,
        allow_null=True
    )
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference_number = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["payment_method_id"].queryset = tenant_active_qs(PaymentMethod, self.context)
        self.fields["bank_account_id"].queryset = tenant_active_qs(BankAccount, self.context)

    def validate_payment_method(self, payment_method):
        shop = require_tenant_shop(self.context)

        if payment_method.shop_id != shop.id:
            raise serializers.ValidationError("Payment method does not belong to your shop.")

        if not payment_method.is_active:
            raise serializers.ValidationError("Payment method is not active.")

        return payment_method

    def validate_bank_account(self, bank_account):
        if bank_account is None:
            return bank_account

        shop = require_tenant_shop(self.context)

        if bank_account.shop_id != shop.id:
            raise serializers.ValidationError("Bank account does not belong to your shop.")

        if not bank_account.is_active:
            raise serializers.ValidationError("Bank account is not active.")

        return bank_account

    def validate(self, attrs):
        payment_method = attrs.get("payment_method")
        bank_account = attrs.get("bank_account")
        amount = attrs.get("amount") or Decimal("0")
        shop = require_tenant_shop(self.context)

        attrs["reference_number"] = clean_str(attrs.get("reference_number"))
        attrs["note"] = clean_str(attrs.get("note"))

        if amount <= 0:
            raise serializers.ValidationError({
                "amount": "Payment amount harus lebih besar dari 0."
            })

        if bank_account and bank_account.shop_id != getattr(shop, "id", None):
            raise serializers.ValidationError({
                "bank_account_id": "Bank account tidak berasal dari shop Anda."
            })

        if payment_method.requires_bank_account and not bank_account:
            raise serializers.ValidationError({
                "bank_account_id": "Bank account wajib dipilih untuk metode pembayaran ini."
            })

        if (
            payment_method.payment_type == PaymentMethod.PaymentType.CASH
            and bank_account is not None
        ):
            raise serializers.ValidationError({
                "bank_account_id": "Metode CASH tidak boleh memakai bank account."
            })

        return attrs


# ==========================================================
# Order
# ==========================================================
class OrderSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.none(),
        required=False,
        allow_null=True
    )

    items = OrderItemSerializer(many=True)
    payments = CheckoutPaymentInputSerializer(many=True, required=False)
    payment_records = SalePaymentSerializer(source="payments", many=True, read_only=True)

    order_type = serializers.ChoiceField(
        choices=Order.OrderType.choices,
        required=False,
        write_only=True
    )

    default_order_type = serializers.ChoiceField(
        choices=Order.OrderType.choices,
        required=False
    )
    table_number = serializers.CharField(required=False, allow_blank=True)
    delivery_address = serializers.CharField(required=False, allow_blank=True)
    delivery_fee = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)

    class Meta:
        model = Order
        fields = [
            "id",
            "invoice_number",
            "customer",
            "created_at",
            "payment_method",
            "subtotal",
            "discount",
            "tax",
            "total",
            "notes",
            "is_paid",
            "order_type",
            "default_order_type",
            "table_number",
            "delivery_address",
            "delivery_fee",
            "items",
            "payments",
            "payment_records",
        ]
        read_only_fields = ["id", "created_at", "invoice_number", "subtotal", "total"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["customer"].queryset = tenant_qs(Customer, self.context)

        self.fields["items"].child.context.update(self.context)
        self.fields["payments"].child.context.update(self.context)

        self.fields["items"].child.fields["product"].queryset = tenant_qs(Product, self.context)
        self.fields["items"].child.fields["weight_unit"].queryset = tenant_qs(Unit, self.context)

        self.fields["payments"].child.fields["payment_method_id"].queryset = tenant_active_qs(
            PaymentMethod, self.context
        )
        self.fields["payments"].child.fields["bank_account_id"].queryset = tenant_active_qs(
            BankAccount, self.context
        )

    def _calculate_subtotal_from_items(self, items):
        subtotal = Decimal("0.00")
        for item in items:
            qty = Decimal(str(item.get("quantity") or 0))
            price = Decimal(str(item.get("price") or 0))
            subtotal += qty * price
        return subtotal

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        if attrs.get("customer") == "":
            attrs["customer"] = None

        attrs["notes"] = clean_str(attrs.get("notes"))
        attrs["table_number"] = clean_str(attrs.get("table_number"))
        attrs["delivery_address"] = clean_str(attrs.get("delivery_address"))

        items = attrs.get("items") or []
        if len(items) == 0:
            raise serializers.ValidationError({"items": "Items cannot be empty."})

        default_item_order_type = (
            OrderItem.OrderType.TAKE_OUT
            if shop.business_type == Shop.BusinessType.RESTAURANT
            else OrderItem.OrderType.GENERAL
        )

        for i in items:
            if not i.get("order_type"):
                i["order_type"] = default_item_order_type

        if shop.business_type in {Shop.BusinessType.RETAIL, Shop.BusinessType.WORKSHOP}:
            if attrs.get("default_order_type") not in (None, "", Order.OrderType.GENERAL):
                raise serializers.ValidationError({
                    "default_order_type": "Only GENERAL order type is allowed for non-restaurant shops."
                })

            if attrs.get("table_number"):
                raise serializers.ValidationError({
                    "table_number": "Table number is only allowed for restaurant shops."
                })

            if attrs.get("delivery_address"):
                raise serializers.ValidationError({
                    "delivery_address": "Delivery address is only allowed for restaurant shops."
                })

            if (attrs.get("delivery_fee") or Decimal("0.00")) != Decimal("0.00"):
                raise serializers.ValidationError({
                    "delivery_fee": "Delivery fee is only allowed for restaurant shops."
                })

            invalid_types = [
                i.get("order_type")
                for i in items
                if i.get("order_type") not in (None, "", OrderItem.OrderType.GENERAL)
            ]
            if invalid_types:
                raise serializers.ValidationError({
                    "items": "Only GENERAL item order type is allowed for non-restaurant shops."
                })

        if shop.business_type == Shop.BusinessType.RESTAURANT:
            has_dine_in = any((i.get("order_type") == OrderItem.OrderType.DINE_IN) for i in items)
            has_delivery = any((i.get("order_type") == OrderItem.OrderType.DELIVERY) for i in items)

            table_number = attrs.get("table_number") or ""
            delivery_address = attrs.get("delivery_address") or ""

            if has_dine_in and not table_number:
                raise serializers.ValidationError({
                    "table_number": "Table number is required for Dine-In."
                })

            if has_delivery and not delivery_address:
                raise serializers.ValidationError({
                    "delivery_address": "Delivery address is required for Delivery."
                })

        discount = attrs.get("discount") or Decimal("0.00")
        tax = attrs.get("tax") or Decimal("0.00")
        delivery_fee = attrs.get("delivery_fee") or Decimal("0.00")
        is_paid = attrs.get("is_paid", True)
        payments = attrs.get("payments", None)

        if discount < 0:
            raise serializers.ValidationError({"discount": "Discount cannot be negative."})
        if tax < 0:
            raise serializers.ValidationError({"tax": "Tax cannot be negative."})
        if delivery_fee < 0:
            raise serializers.ValidationError({"delivery_fee": "Delivery fee cannot be negative."})

        computed_subtotal = self._calculate_subtotal_from_items(items)
        computed_total = computed_subtotal + delivery_fee - discount + tax

        if computed_total < 0:
            raise serializers.ValidationError({"total": "Total order cannot be negative."})

        attrs["subtotal"] = computed_subtotal
        attrs["total"] = computed_total

        if is_paid and (payments is None or len(payments) == 0):
            raise serializers.ValidationError({
                "payments": "At least one payment is required for paid orders."
            })

        if not is_paid and payments:
            raise serializers.ValidationError({
                "payments": "Open/unpaid order should not include payment records."
            })

        if payments:
            payment_total = sum((p.get("amount") or Decimal("0")) for p in payments)
            if payment_total != computed_total:
                raise serializers.ValidationError({
                    "payments": f"Total pembayaran ({payment_total}) harus sama dengan total order ({computed_total})."
                })

        return attrs
    
    def _get_payment_method_summary(self, payments_data):
        if not payments_data:
            return "UNPAID"

        unique_types = {p["payment_method"].payment_type for p in payments_data}
        unique_codes = {p["payment_method"].code for p in payments_data}

        if len(payments_data) > 1:
            return "SPLIT"

        if len(unique_codes) == 1:
            return list(unique_codes)[0]

        if len(unique_types) == 1:
            return list(unique_types)[0]

        return "MIXED"

    def _create_bank_ledger_for_payment(self, *, order, payment_obj, user=None):
        bank_account = payment_obj.bank_account
        if not bank_account:
            return

        before = bank_account.current_balance or Decimal("0.00")
        after = before + payment_obj.amount

        BankLedger.objects.create(
            bank_account=bank_account,
            transaction_type=BankLedger.TransactionType.SALE_IN,
            direction=BankLedger.Direction.IN,
            amount=payment_obj.amount,
            balance_before=before,
            balance_after=after,
            reference_order=order,
            reference_payment=payment_obj,
            description=f"Payment for order {order.invoice_number or order.id}",
            created_by=user,
        )

        bank_account.current_balance = after
        bank_account.save(update_fields=["current_balance"])

    @transaction.atomic
    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        user = require_authenticated_user(self.context)

        items_data = validated_data.pop("items")
        payments_data = validated_data.pop("payments", [])
        validated_data.pop("order_type", None)

        validated_data["notes"] = clean_str(validated_data.get("notes"))
        validated_data["table_number"] = clean_str(validated_data.get("table_number"))
        validated_data["delivery_address"] = clean_str(validated_data.get("delivery_address"))

        types = {
            (
                it.get("order_type")
                or (
                    OrderItem.OrderType.TAKE_OUT
                    if shop.business_type == Shop.BusinessType.RESTAURANT
                    else OrderItem.OrderType.GENERAL
                )
            )
            for it in items_data
        }
        types = {t for t in types if t}
        computed_default_type = list(types)[0] if len(types) == 1 else Order.OrderType.GENERAL
        validated_data["default_order_type"] = computed_default_type

        discount = validated_data.get("discount") or Decimal("0.00")
        tax = validated_data.get("tax") or Decimal("0.00")
        delivery_fee = validated_data.get("delivery_fee") or Decimal("0.00")
        is_paid = validated_data.get("is_paid", True)

        locked_products = {}
        subtotal = Decimal("0.00")

        for item_data in items_data:
            product_ref = item_data["product"]
            quantity = Decimal(str(item_data["quantity"]))
            price = Decimal(str(item_data["price"]))

            product = Product.objects.select_for_update().get(pk=product_ref.pk, shop=shop)
            locked_products[product.pk] = product

            if product.track_stock and product.stock < quantity:
                raise serializers.ValidationError({
                    "stock": f"Insufficient stock for {product.name}. Remaining {product.stock}, requested {quantity}"
                })

            subtotal += quantity * price

        total = subtotal + delivery_fee - discount + tax
        if total < 0:
            raise serializers.ValidationError({"total": "Total order cannot be negative."})

        payment_summary = self._get_payment_method_summary(payments_data)

        validated_data["subtotal"] = subtotal
        validated_data["total"] = total
        validated_data["payment_method"] = payment_summary
        validated_data["is_paid"] = is_paid
        validated_data = inject_shop_if_supported(Order, validated_data, shop)

        if model_has_field(Order, "served_by") and "served_by" not in validated_data:
            validated_data["served_by"] = user

        order = Order.objects.create(**validated_data)

        for item_data in items_data:
            locked_product = locked_products[item_data["product"].pk]
            quantity = Decimal(str(item_data["quantity"]))
            price = Decimal(str(item_data["price"]))

            order_item_type = item_data.get("order_type") or (
                OrderItem.OrderType.TAKE_OUT
                if shop.business_type == Shop.BusinessType.RESTAURANT
                else OrderItem.OrderType.GENERAL
            )

            OrderItem.objects.create(
                order=order,
                product=locked_product,
                quantity=item_data["quantity"],
                price=price,
                weight_unit=item_data.get("weight_unit"),
                order_type=order_item_type,
            )

            if locked_product.track_stock:
                before = locked_product.stock
                after = before - quantity

                locked_product.stock = after
                locked_product.save(update_fields=["stock"])

                StockMovement.objects.create(
                    shop=shop,
                    product=locked_product,
                    movement_type=StockMovement.Type.SALE,
                    quantity_delta=-quantity,
                    before_stock=before,
                    after_stock=after,
                    note=f"Order #{order.id}",
                    ref_model="Order",
                    ref_id=order.id,
                    created_by=user,
                )

        if payments_data:
            payment_total = Decimal("0.00")

            for payment_data in payments_data:
                payment_method = payment_data["payment_method"]
                bank_account = payment_data.get("bank_account")

                if payment_method.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "payments": "Payment method does not belong to this shop."
                    })

                if bank_account and bank_account.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "payments": "Bank account does not belong to this shop."
                    })

                payment_obj = SalePayment.objects.create(
                    order=order,
                    payment_method=payment_method,
                    bank_account=bank_account,
                    amount=payment_data["amount"],
                    reference_number=clean_str(payment_data.get("reference_number")),
                    note=clean_str(payment_data.get("note")),
                    created_by=user,
                )

                payment_total += payment_obj.amount

                if payment_obj.bank_account:
                    self._create_bank_ledger_for_payment(
                        order=order,
                        payment_obj=payment_obj,
                        user=user,
                    )

            if payment_total != order.total:
                raise serializers.ValidationError({
                    "payments": f"Total pembayaran ({payment_total}) tidak sama dengan total order ({order.total})."
                })

        return order


# ==========================================================
# Expense / Banner / Shop
# ==========================================================
class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = ["id", "name", "note", "amount", "date", "time"]

    def validate(self, attrs):
        require_tenant_shop(self.context)

        name = clean_str(attrs.get("name") or getattr(self.instance, "name", ""))
        note = clean_str(attrs.get("note"))
        amount = attrs.get("amount")

        if not name:
            raise serializers.ValidationError({"name": "Expense name is required."})

        if amount is None or amount < 0:
            raise serializers.ValidationError({"amount": "Amount must be 0 or greater."})

        attrs["name"] = name
        attrs["note"] = note
        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        validated_data = inject_shop_if_supported(Expense, validated_data, shop)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


class BannerSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ["id", "title", "image_url"]

    def get_image_url(self, obj):
        request = self.context.get("request")
        return _normalize_media_url(request, obj.image)

class ShopFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopFeature
        fields = [
            "enable_dine_in",
            "enable_takeaway",
            "enable_delivery",
            "enable_table_number",
            "enable_barcode_scan",
            "enable_customer_points",
            "enable_split_payment",
            "enable_service_fee",
            "enable_mechanic",
            "enable_vehicle_info",
            "show_product_images_in_pos",
            "use_grid_pos_layout",
        ]        

class ShopSerializer(serializers.ModelSerializer):
    logo = serializers.ImageField(required=False, allow_null=True)
    all_category_icon = serializers.ImageField(required=False, allow_null=True)

    logo_url = serializers.SerializerMethodField()
    all_category_icon_url = serializers.SerializerMethodField()
    features = ShopFeatureSerializer(read_only=True)

    class Meta:
        model = Shop
        fields = [
            "id",
            "name",
            "code",
            "slug",
            "business_type",
            "address",
            "phone",
            "email",
            "logo",
            "all_category_icon",
            "logo_url",
            "all_category_icon_url",
            "features",
        ]
        read_only_fields = [
            "id",
            "code",
            "slug",
            "logo_url",
            "all_category_icon_url",
            "features",
        ]

    def get_logo_url(self, obj):
        request = self.context.get("request")
        return _normalize_media_url(request, obj.logo) or ""

    def get_all_category_icon_url(self, obj):
        request = self.context.get("request")
        return _normalize_media_url(request, obj.all_category_icon) or ""

    def validate(self, attrs):
        require_tenant_shop(self.context)

        if "name" in attrs:
            attrs["name"] = clean_str(attrs.get("name"))
        if "address" in attrs:
            attrs["address"] = clean_str(attrs.get("address"))
        if "phone" in attrs:
            attrs["phone"] = clean_str(attrs.get("phone"))
        if "email" in attrs:
            attrs["email"] = clean_str(attrs.get("email"))

        return attrs

    def update(self, instance, validated_data):
        shop = require_tenant_shop(self.context)
        if instance.id != shop.id:
            raise serializers.ValidationError("You cannot edit another shop.")
        return super().update(instance, validated_data)


# ==========================================================
# Lite serializers
# ==========================================================
class ProductLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "code", "sku", "item_type", "track_stock", "sell_price"]


class CustomerLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name"]


class UserLiteSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name"]

    def get_display_name(self, obj):
        full_name = ""
        if hasattr(obj, "get_full_name"):
            full_name = obj.get_full_name().strip()
        return full_name or obj.username


# ==========================================================
# Staff / Shop User
# ==========================================================
class StaffSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField(read_only=True)
    role_label = serializers.SerializerMethodField(read_only=True)
    shop_id = serializers.IntegerField(source="shop.id", read_only=True)
    shop_name = serializers.CharField(source="shop.name", read_only=True)
    shop_code = serializers.CharField(source="shop.code", read_only=True)

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "full_name",
            "first_name",
            "last_name",
            "email",
            "role",
            "role_label",
            "shop_id",
            "shop_name",
            "shop_code",
            "is_active",
            "date_joined",
            "password",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "role_label",
            "shop_id",
            "shop_name",
            "shop_code",
            "date_joined",
        ]
        extra_kwargs = {
            "username": {"required": True},
            "first_name": {"required": False, "allow_blank": True},
            "last_name": {"required": False, "allow_blank": True},
            "email": {"required": False, "allow_blank": True},
            "role": {"required": True},
            "is_active": {"required": False},
        }

    def get_full_name(self, obj):
        if hasattr(obj, "get_full_name"):
            return obj.get_full_name().strip() or obj.username
        return obj.username

    def get_role_label(self, obj):
        return getattr(obj, "role_label", obj.role)

    def validate(self, attrs):
        user = require_authenticated_user(self.context)
        shop = require_tenant_shop(self.context)

        username = clean_str(attrs.get("username") or getattr(self.instance, "username", ""))
        email = clean_str(attrs.get("email") or getattr(self.instance, "email", ""))
        first_name = clean_str(attrs.get("first_name") or getattr(self.instance, "first_name", ""))
        last_name = clean_str(attrs.get("last_name") or getattr(self.instance, "last_name", ""))
        role = clean_str(attrs.get("role") or getattr(self.instance, "role", "")).lower()

        if not username:
            raise serializers.ValidationError({"username": "Username is required."})

        allowed_roles = {"owner", "manager", "cashier"}
        if role not in allowed_roles:
            raise serializers.ValidationError({
                "role": "Role must be one of: owner, manager, cashier."
            })

        attrs["username"] = username
        attrs["email"] = email
        attrs["first_name"] = first_name
        attrs["last_name"] = last_name
        attrs["role"] = role

        qs = User.objects.filter(username__iexact=username)
        if not user.is_superuser:
            qs = qs.filter(shop=shop)

        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise serializers.ValidationError({
                "username": "Username already exists in this shop."
            })

        if email:
            email_qs = User.objects.filter(email__iexact=email)
            if not user.is_superuser:
                email_qs = email_qs.filter(shop=shop)

            if self.instance:
                email_qs = email_qs.exclude(pk=self.instance.pk)

            if email_qs.exists():
                raise serializers.ValidationError({
                    "email": "Email already exists in this shop."
                })

        password = attrs.get("password", None)
        if not self.instance and not password:
            raise serializers.ValidationError({
                "password": "Password is required when creating staff."
            })

        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", None)

        user = User(
            **validated_data,
            is_staff=False,
            is_superuser=False,
        )

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save()
        return user

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)

        password = validated_data.pop("password", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if hasattr(instance, "shop_id"):
            shop = require_tenant_shop(self.context)
            instance.shop = shop

        if password:
            instance.set_password(password)

        instance.save()
        return instance

# ==========================================================
# Stock Adjustment
# ==========================================================
class StockAdjustmentSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    product_name = serializers.CharField(source="product.name", read_only=True)
    adjusted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "product",
            "product_name",
            "old_stock",
            "new_stock",
            "reason",
            "note",
            "adjusted_at",
            "adjusted_by",
            "adjusted_by_name",
        ]
        read_only_fields = [
            "id",
            "product_name",
            "old_stock",
            "adjusted_at",
            "adjusted_by",
            "adjusted_by_name",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = tenant_qs(Product, self.context)

    def get_adjusted_by_name(self, obj):
        if not obj.adjusted_by:
            return ""
        return (
            getattr(obj.adjusted_by, "get_full_name", lambda: "")().strip()
            or getattr(obj.adjusted_by, "username", "")
        )

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        product = attrs.get("product")
        new_stock = attrs.get("new_stock")
        reason = clean_str(attrs.get("reason"))
        note = clean_str(attrs.get("note"))

        if product and product.shop_id != shop.id:
            raise serializers.ValidationError({"product": "Product does not belong to your shop."})

        if product and not product.track_stock:
            raise serializers.ValidationError({
                "product": "This item does not use stock adjustment."
            })

        if new_stock is None or new_stock < 0:
            raise serializers.ValidationError({"new_stock": "New stock must be 0 or greater."})

        if not reason:
            raise serializers.ValidationError({"reason": "Reason is required."})

        attrs["reason"] = reason
        attrs["note"] = note
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        user = require_authenticated_user(self.context)

        product_ref = validated_data["product"]
        new_stock = validated_data["new_stock"]

        product = Product.objects.select_for_update().get(pk=product_ref.pk, shop=shop)
        old_stock = product.stock

        validated_data["product"] = product
        validated_data["old_stock"] = old_stock
        validated_data["adjusted_by"] = user
        validated_data = inject_shop_if_supported(StockAdjustment, validated_data, shop)

        adjustment = StockAdjustment.objects.create(**validated_data)

        product.stock = new_stock
        product.save(update_fields=["stock"])

        StockMovement.objects.create(
            shop=shop,
            product=product,
            movement_type=StockMovement.Type.ADJUSTMENT,
            quantity_delta=(new_stock - old_stock),
            before_stock=old_stock,
            after_stock=new_stock,
            note=f"StockAdjustment #{adjustment.id}: {adjustment.reason}",
            ref_model="StockAdjustment",
            ref_id=adjustment.id,
            created_by=user,
        )

        return adjustment

    def update(self, instance, validated_data):
        raise serializers.ValidationError("Stock adjustment records cannot be edited once created.")


# ==========================================================
# Inventory Count
# ==========================================================
class InventoryCountItemSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    difference = serializers.ReadOnlyField()

    product_name = serializers.CharField(source="product.name", read_only=True)
    cost_price = serializers.DecimalField(
        source="product.buy_price",
        max_digits=10,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = InventoryCountItem
        fields = [
            "id",
            "product",
            "product_name",
            "system_stock",
            "counted_stock",
            "difference",
            "cost_price",
        ]
        read_only_fields = ["id", "system_stock", "difference", "product_name", "cost_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = tenant_qs(Product, self.context)

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)
        product = attrs.get("product")
        counted_stock = attrs.get("counted_stock")

        if product and product.shop_id != shop.id:
            raise serializers.ValidationError({"product": "Product does not belong to your shop."})

        if product and not product.track_stock:
            raise serializers.ValidationError({
                "product": "This item does not use inventory counting."
            })

        if counted_stock is None or counted_stock < 0:
            raise serializers.ValidationError({"counted_stock": "Counted stock must be 0 or greater."})

        return attrs

class InventoryCountSerializer(serializers.ModelSerializer):
    items = InventoryCountItemSerializer(many=True, required=False)
    counted_by = UserLiteSerializer(read_only=True)

    class Meta:
        model = InventoryCount
        fields = ["id", "title", "note", "status", "counted_at", "counted_by", "items"]
        read_only_fields = ["id", "counted_at", "counted_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        product_qs = tenant_qs(Product, self.context)

        if "items" in self.fields:
            child = self.fields["items"].child
            child.context.update(self.context)

            if "product" in child.fields:
                child.fields["product"].queryset = product_qs

    def validate(self, attrs):
        require_tenant_shop(self.context)

        if "title" in attrs:
            attrs["title"] = clean_str(attrs.get("title"))
        if "note" in attrs:
            attrs["note"] = clean_str(attrs.get("note"))

        return attrs

    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        user = require_authenticated_user(self.context)
        items_data = validated_data.pop("items", [])

        validated_data = inject_shop_if_supported(InventoryCount, validated_data, shop)
        if model_has_field(InventoryCount, "counted_by"):
            validated_data["counted_by"] = user

        with transaction.atomic():
            obj = InventoryCount.objects.create(**validated_data)

            for it in items_data:
                product = it["product"]
                if product.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' does not belong to this shop."
                    })

                system_stock = getattr(product, "stock", 0)
                counted_stock = it["counted_stock"]

                InventoryCountItem.objects.create(
                    inventory=obj,
                    product=product,
                    system_stock=system_stock,
                    counted_stock=counted_stock,
                )

        return obj

    def update(self, instance, validated_data):
        ensure_instance_belongs_to_shop(instance, self.context)
        return super().update(instance, validated_data)


# ==========================================================
# Product Return
# ==========================================================
class ProductReturnItemSerializer(serializers.ModelSerializer):
    product = ProductLiteSerializer(read_only=True)

    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.none(),
        source="product",
        write_only=True,
        required=False
    )

    product_pk = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.none(),
        source="product",
        write_only=True,
        required=False
    )

    class Meta:
        model = ProductReturnItem
        fields = ["id", "product", "product_id", "product_pk", "quantity", "unit_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = tenant_qs(Product, self.context)
        self.fields["product_id"].queryset = qs
        self.fields["product_pk"].queryset = qs

    def validate(self, attrs):
        product = attrs.get("product")
        quantity = attrs.get("quantity")
        unit_price = attrs.get("unit_price")

        if product is None:
            raise serializers.ValidationError({"product_id": "product_id/product is required"})

        if quantity is None or quantity <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than 0."})

        if unit_price is not None and unit_price < 0:
            raise serializers.ValidationError({"unit_price": "Unit price must be 0 or greater."})

        return attrs


class ProductReturnSerializer(serializers.ModelSerializer):
    returned_by = UserLiteSerializer(read_only=True)

    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.none(),
        required=False,
        allow_null=True
    )

    customer = CustomerLiteSerializer(read_only=True)
    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.none(),
        source="customer",
        write_only=True,
        required=False,
        allow_null=True
    )

    items = ProductReturnItemSerializer(many=True)
    invoice_number = serializers.CharField(source="order.invoice_number", read_only=True)

    class Meta:
        model = ProductReturn
        fields = [
            "id",
            "order",
            "invoice_number",
            "customer",
            "customer_id",
            "note",
            "returned_at",
            "returned_by",
            "items",
        ]
        read_only_fields = ["id", "returned_at", "returned_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["customer_id"].queryset = tenant_qs(Customer, self.context)
        self.fields["order"].queryset = tenant_qs(Order, self.context)

        # FIX nested items queryset
        product_qs = tenant_qs(Product, self.context)
        if "items" in self.fields:
            child = self.fields["items"].child

            if "product_id" in child.fields:
                child.fields["product_id"].queryset = product_qs

            if "product_pk" in child.fields:
                child.fields["product_pk"].queryset = product_qs

    def validate(self, attrs):
        shop = require_tenant_shop(self.context)

        attrs["note"] = clean_str(attrs.get("note"))

        order = attrs.get("order")
        customer = attrs.get("customer")
        items = attrs.get("items") or []

        if not items:
            raise serializers.ValidationError({"items": "Items cannot be empty."})

        if order:
            if getattr(order, "shop_id", None) != shop.id:
                raise serializers.ValidationError({"order": "Order does not belong to your shop."})

            if customer and getattr(order, "customer_id", None) and order.customer_id != customer.id:
                raise serializers.ValidationError({
                    "customer_id": "Customer must match the selected order."
                })

            order_qty_map = {}
            for row in OrderItem.objects.filter(order=order).values("product_id").annotate(
                total_qty=Sum("quantity")
            ):
                order_qty_map[row["product_id"]] = row["total_qty"] or 0

            prior_return_map = {}
            for row in ProductReturnItem.objects.filter(
                product_return__order=order
            ).values("product_id").annotate(total_qty=Sum("quantity")):
                prior_return_map[row["product_id"]] = row["total_qty"] or 0

            current_return_map = {}
            for item in items:
                product = item["product"]
                qty = item["quantity"]

                if product.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' does not belong to your shop."
                    })

                sold_qty = order_qty_map.get(product.id, 0)
                if sold_qty <= 0:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' is not part of the selected order."
                    })

                current_return_map[product.id] = current_return_map.get(product.id, 0) + qty

            for product_id, qty_to_return_now in current_return_map.items():
                sold_qty = order_qty_map.get(product_id, 0)
                already_returned = prior_return_map.get(product_id, 0)
                remaining_qty = sold_qty - already_returned

                if qty_to_return_now > remaining_qty:
                    raise serializers.ValidationError({
                        "items": (
                            f"Return quantity exceeds remaining sold quantity for product ID {product_id}. "
                            f"Remaining: {remaining_qty}, requested: {qty_to_return_now}"
                        )
                    })
        else:
            for item in items:
                product = item["product"]
                if product.shop_id != shop.id:
                    raise serializers.ValidationError({
                        "items": f"Product '{product.name}' does not belong to your shop."
                    })

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        shop = require_tenant_shop(self.context)
        user = require_authenticated_user(self.context)

        items = validated_data.pop("items", [])
        validated_data = inject_shop_if_supported(ProductReturn, validated_data, shop)

        if model_has_field(ProductReturn, "returned_by"):
            validated_data["returned_by"] = user

        ret = ProductReturn.objects.create(**validated_data)

        for it in items:
            product_ref = it["product"]
            qty = Decimal(str(it.get("quantity", 1)))
            unit_price = it.get("unit_price")
            product = Product.objects.select_for_update().get(pk=product_ref.pk, shop=shop)

            if unit_price is None:
                unit_price = product.sell_price or Decimal("0.00")

            if product.track_stock:
                before = product.stock
                after = before + qty

                product.stock = after
                product.save(update_fields=["stock"])
            else:
                before = product.stock
                after = product.stock

            ProductReturnItem.objects.create(
                product_return=ret,
                product=product,
                quantity=qty,
                unit_price=unit_price,
            )

            if product.track_stock:
                StockMovement.objects.create(
                    shop=shop,
                    product=product,
                    movement_type=StockMovement.Type.SALE_RETURN,
                    quantity_delta=qty,
                    before_stock=before,
                    after_stock=after,
                    note=f"ProductReturn #{ret.id}",
                    ref_model="ProductReturn",
                    ref_id=ret.id,
                    created_by=user,
                )

        return ret

# ==========================================================
# Stock Movement
# ==========================================================
class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "created_at", "movement_type", "quantity_delta",
            "before_stock", "after_stock", "note", "ref_model", "ref_id",
            "product", "product_name", "product_code", "product_sku",
            "created_by",
        ]