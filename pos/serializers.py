from rest_framework import serializers
from django.db import transaction
from django.db.models import F
from django.contrib.auth import get_user_model

from .models import (
    Customer, Supplier, Product, Category, Unit, Banner,
    Order, OrderItem, Shop, Expense,
    StockAdjustment, InventoryCount, InventoryCountItem,
    ProductReturn, ProductReturnItem, StockMovement
)

User = get_user_model()


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


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = "__all__"


class CategorySerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "icon_url"]

    def get_icon_url(self, obj):
        request = self.context.get("request")
        try:
            if not obj.icon:
                return None
            url = _force_https(obj.icon.url)
            return _abs_or_raw(request, url)
        except Exception:
            return None


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image = serializers.ImageField(use_url=True, required=False, allow_null=True)

    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source="category",
        write_only=True,
        required=False,
        allow_null=True,
    )

    supplier = SupplierSerializer(read_only=True)
    supplier_id = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(),
        source="supplier",
        write_only=True,
        required=False,
        allow_null=True,
    )

    unit = UnitSerializer(read_only=True)
    unit_id = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(),
        source="unit",
        write_only=True,
        required=False,
        allow_null=True,
    )

    def get_image_url(self, obj):
        request = self.context.get("request")
        try:
            if not obj.image:
                return None
            url = _force_https(obj.image.url)
            return _abs_or_raw(request, url)
        except Exception:
            return None

    class Meta:
        model = Product
        fields = [
            "id", "name",
            "sku",           
            "code",          
            "description", "stock",
            "buy_price", "sell_price", "weight",
            "image", "image_url",
            "category", "category_id",
            "supplier", "supplier_id",
            "unit", "unit_id",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    weight_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(),
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


class OrderSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True
    )
    items = OrderItemSerializer(many=True)

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
            "customer", "created_at", "payment_method", "subtotal",
            "discount", "tax", "total", "notes", "is_paid",
            "order_type",
            "default_order_type", "table_number", "delivery_address", "delivery_fee",
            "items",
        ]
        read_only_fields = ["id", "created_at", "invoice_number"]  # ✅ invoice auto

    def validate(self, attrs):
        if attrs.get("customer") == "":
            attrs["customer"] = None

        items = attrs.get("items") or []
        if len(items) == 0:
            raise serializers.ValidationError({"items": "Items cannot be empty."})

        for i in items:
            if not i.get("order_type"):
                i["order_type"] = OrderItem.OrderType.TAKE_OUT

        has_dine_in = any((i.get("order_type") == "DINE_IN") for i in items)
        has_delivery = any((i.get("order_type") == "DELIVERY") for i in items)

        table_number = (attrs.get("table_number") or "").strip()
        delivery_address = (attrs.get("delivery_address") or "").strip()

        if has_dine_in and not table_number:
            raise serializers.ValidationError({"table_number": "Table number is required for Dine-In."})

        if has_delivery and not delivery_address:
            raise serializers.ValidationError({"delivery_address": "Delivery address is required for Delivery."})

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        validated_data.pop("order_type", None)

        types = {(it.get("order_type") or OrderItem.OrderType.TAKE_OUT) for it in items_data}
        types = {t for t in types if t}
        computed = list(types)[0] if len(types) == 1 else Order.OrderType.GENERAL
        validated_data["default_order_type"] = computed

        if "delivery_fee" not in validated_data:
            validated_data["delivery_fee"] = 0

        order = Order.objects.create(**validated_data)

        for item_data in items_data:
            product = item_data["product"]
            quantity = int(item_data["quantity"])
            product.refresh_from_db()

            if product.stock < quantity:
                raise serializers.ValidationError({
                    "stock": f"Insufficient stock for {product.name}. Remaining {product.stock}, requested {quantity}"
                })

            if "order_type" not in item_data:
                item_data["order_type"] = OrderItem.OrderType.TAKE_OUT

            before = product.stock
            after = before - quantity

            Product.objects.filter(id=product.id).update(stock=F("stock") - quantity)
            OrderItem.objects.create(order=order, **item_data)

            # ✅ inventory history
            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.Type.SALE,
                quantity_delta=-quantity,
                before_stock=before,
                after_stock=after,
                note=f"Order #{order.id}",
                ref_model="Order",
                ref_id=order.id,
                created_by=validated_data.get("served_by"),
            )

        return order


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = ["id", "name", "note", "amount", "date", "time"]


class BannerSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ["id", "title", "image_url"]

    def get_image_url(self, obj):
        request = self.context.get("request")
        try:
            if not obj.image:
                return None
            url = _force_https(obj.image.url)
            return _abs_or_raw(request, url)
        except Exception:
            return None


class ShopSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    all_category_icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = ["id", "name", "address", "phone", "email", "logo_url", "all_category_icon_url"]

    def get_logo_url(self, obj):
        try:
            if not obj.logo:
                return ""
            return _force_https(obj.logo.url) or ""
        except Exception:
            return ""

    def get_all_category_icon_url(self, obj):
        try:
            if not obj.all_category_icon:
                return ""
            return _force_https(obj.all_category_icon.url) or ""
        except Exception:
            return ""


# ==========================================================
# Inventory serializers
# ==========================================================

class ProductLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "code", "sku", "sell_price"]


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
        return getattr(obj, "full_name", "") or obj.username

class StockAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockAdjustment
        fields = "__all__"


class InventoryCountItemSerializer(serializers.ModelSerializer):
    difference = serializers.IntegerField(read_only=True)

    class Meta:
        model = InventoryCountItem
        fields = ["id", "product", "system_stock", "counted_stock", "difference"]


class InventoryCountSerializer(serializers.ModelSerializer):
    items = InventoryCountItemSerializer(many=True)
    
    class UserLiteSerializer(serializers.ModelSerializer):
        display_name = serializers.SerializerMethodField()

        class Meta:
            model = User
            fields = ["id", "username", "display_name"]

        def get_display_name(self, obj):
            return getattr(obj, "full_name", "") or obj.username

    class ProductLiteSerializer(serializers.ModelSerializer):
        class Meta:
            model = Product
            fields = ["id", "name", "code", "sku", "sell_price"]


    class CustomerLiteSerializer(serializers.ModelSerializer):
        class Meta:
            model = Customer
            fields = ["id", "name"]

    class Meta:
        model = InventoryCount
        fields = ["id", "title", "note", "counted_at", "counted_by", "items"]

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        count = InventoryCount.objects.create(**validated_data)

        for it in items:
            product = it["product"]
            product.refresh_from_db()

            system_stock = int(it.get("system_stock", product.stock))
            counted_stock = int(it.get("counted_stock", product.stock))
            diff = counted_stock - system_stock

            InventoryCountItem.objects.create(
                count=count,
                product=product,
                system_stock=system_stock,
                counted_stock=counted_stock
            )

            if diff != 0:
                before = product.stock
                after = counted_stock
                Product.objects.filter(id=product.id).update(stock=counted_stock)

                StockMovement.objects.create(
                    product=product,
                    movement_type=StockMovement.Type.COUNT,
                    quantity_delta=diff,
                    before_stock=before,
                    after_stock=after,
                    note=f"InventoryCount #{count.id}",
                    ref_model="InventoryCount",
                    ref_id=count.id,
                    created_by=validated_data.get("counted_by"),
                )

        return count


class ProductReturnItemSerializer(serializers.ModelSerializer):
    # READ: tampilkan object product (nama, sku, dll)
    product = ProductLiteSerializer(read_only=True)

    # WRITE: tetap boleh kirim product_id (recommended)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source="product",
        write_only=True,
        required=False
    )

    # COMPAT: kalau client lama masih kirim "product": 3 (int), tetap diterima
    product_pk = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source="product",
        write_only=True,
        required=False
    )

    class Meta:
        model = ProductReturnItem
        fields = ["id", "product", "product_id", "product_pk", "quantity", "unit_price"]

    def validate(self, attrs):
        # pastikan minimal ada product dari salah satu field
        if "product" not in attrs:
            raise serializers.ValidationError({"product_id": "product_id/product is required"})
        return attrs


class ProductReturnSerializer(serializers.ModelSerializer):
    # READ
    returned_by = UserLiteSerializer(read_only=True)

    customer = CustomerLiteSerializer(read_only=True)
    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
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

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])

        # returned_by sebaiknya di-set dari viewset perform_create()
        ret = ProductReturn.objects.create(**validated_data)

        for it in items:
            product = it["product"]
            qty = int(it.get("quantity", 1))
            unit_price = it.get("unit_price", product.sell_price or 0)

            product.refresh_from_db()
            before = product.stock
            after = before + qty

            Product.objects.filter(id=product.id).update(stock=F("stock") + qty)

            ProductReturnItem.objects.create(
                product_return=ret,
                product=product,
                quantity=qty,
                unit_price=unit_price,
            )

            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.Type.SALE_RETURN,
                quantity_delta=qty,
                before_stock=before,
                after_stock=after,
                note=f"ProductReturn #{ret.id}",
                ref_model="ProductReturn",
                ref_id=ret.id,
                created_by=validated_data.get("returned_by"),
            )

        return ret


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
