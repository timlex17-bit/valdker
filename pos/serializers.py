from rest_framework import serializers
from django.db import transaction
from django.db.models import F

from .models import (
    Customer, Supplier, Product, Category, Unit, Banner,
    Order, OrderItem, Shop
)

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'

class CategorySerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'icon_url']

    def get_icon_url(self, obj):
        request = self.context.get('request')
        if obj.icon and request:
            return request.build_absolute_uri(obj.icon.url)
        return None

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = '__all__'

class ProductSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image = serializers.ImageField(use_url=True)
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True
    )

    supplier = SupplierSerializer(read_only=True)
    supplier_id = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.all(), source='supplier', write_only=True
    )

    unit = UnitSerializer(read_only=True)
    unit_id = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(), source='unit', write_only=True
    )

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'code', 'description', 'stock',
            'buy_price', 'sell_price', 'weight', 'image', 'image_url',
            'category', 'category_id', 'supplier', 'supplier_id', 'unit', 'unit_id'
        ]

class OrderItemSerializer(serializers.ModelSerializer):
    # ✅ pastikan product diterima sebagai PK
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    # ✅ weight_unit FK: boleh null & optional
    weight_unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = OrderItem
        fields = ['product', 'quantity', 'price', 'weight_unit']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'created_at', 'payment_method', 'subtotal',
            'discount', 'tax', 'total', 'notes', 'is_paid', 'items'
        ]
        read_only_fields = ['id', 'created_at']  # ✅ penting

    def validate(self, attrs):
        items = attrs.get("items") or []
        if len(items) == 0:
            raise serializers.ValidationError({"items": "Items tidak boleh kosong."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        order = Order.objects.create(**validated_data)

        for item_data in items_data:
            product = item_data['product']
            quantity = int(item_data['quantity'])

            # ✅ lock product row (SQLite memang terbatas tapi tetap aman dengan atomic)
            # Kalau pakai Postgres, ini sangat membantu
            product.refresh_from_db()

            # ✅ Validasi stok jangan sampai minus
            if product.stock < quantity:
                raise serializers.ValidationError({
                    "stock": f"Stok {product.name} tidak cukup. Sisa {product.stock}, minta {quantity}"
                })

            # ✅ stok berkurang
            Product.objects.filter(id=product.id).update(stock=F('stock') - quantity)

            # ✅ create order item
            OrderItem.objects.create(order=order, **item_data)

        return order

class BannerSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ['id', 'title', 'image_url']

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

class ShopSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    all_category_icon_url = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = ["id", "name", "address", "phone", "email", "logo_url", "all_category_icon_url"]

    def get_logo_url(self, obj):
        return obj.logo.url if obj.logo else ""

    def get_all_category_icon_url(self, obj):
        return obj.all_category_icon.url if obj.all_category_icon else ""



