from rest_framework import serializers
from django.db import transaction
from .models import Expense
from django.db.models import F

from .models import (
    Customer, Supplier, Product, Category, Unit, Banner,
    Order, OrderItem, Shop
)


def _force_https(url: str | None) -> str | None:
    """Cloudinary kadang return http, paksa jadi https supaya aman di semua frontend."""
    if not url:
        return url
    return url.replace("http://", "https://")


def _abs_or_raw(request, url: str | None) -> str | None:
    """
    Kalau url relative (/media/..), jadikan absolute pakai request.
    Kalau url sudah absolute (http/https), return apa adanya.
    """
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
            url = obj.icon.url
            url = _force_https(url)
            return _abs_or_raw(request, url)
        except Exception:
            return None


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = "__all__"


class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    # tetap ada untuk upload/edit, dan untuk response juga tetap tampil
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
            url = obj.image.url
            url = _force_https(url)
            return _abs_or_raw(request, url)
        except Exception:
            return None

    class Meta:
        model = Product
        fields = [
            "id", "name", "code", "description", "stock",
            "buy_price", "sell_price", "weight", "image", "image_url",
            "category", "category_id", "supplier", "supplier_id", "unit", "unit_id",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    # ✅ pastikan product diterima sebagai PK
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    # ✅ weight_unit FK: boleh null & optional
    weight_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = OrderItem
        fields = ["product", "quantity", "price", "weight_unit"]


class OrderSerializer(serializers.ModelSerializer):
    # ✅ customer optional
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True
    )

    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = [
            "id", "customer", "created_at", "payment_method", "subtotal",
            "discount", "tax", "total", "notes", "is_paid", "items",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        # ✅ kalau frontend kirim customer: "" (string kosong), treat as None
        if attrs.get("customer") == "":
            attrs["customer"] = None

        items = attrs.get("items") or []
        if len(items) == 0:
            raise serializers.ValidationError({"items": "Items tidak boleh kosong."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")

        # ✅ pastikan customer tidak wajib
        # (kalau tidak ada key 'customer', Order.objects.create akan aman)
        order = Order.objects.create(**validated_data)

        for item_data in items_data:
            product = item_data["product"]
            quantity = int(item_data["quantity"])

            product.refresh_from_db()

            if product.stock < quantity:
                raise serializers.ValidationError({
                    "stock": f"Stok {product.name} tidak cukup. Sisa {product.stock}, minta {quantity}"
                })

            Product.objects.filter(id=product.id).update(stock=F("stock") - quantity)
            OrderItem.objects.create(order=order, **item_data)

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
            url = obj.image.url
            url = _force_https(url)
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
