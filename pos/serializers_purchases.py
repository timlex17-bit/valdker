from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import serializers

from .models import Purchase, PurchaseItem, Supplier, Product, StockMovement


# ==========================================================
# READ serializers
# ==========================================================
class PurchaseItemSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = PurchaseItem
        fields = [
            "id",
            "product_id",
            "product_name",
            "product_code",
            "quantity",
            "cost_price",
            "expired_date",
        ]


class PurchaseListSerializer(serializers.ModelSerializer):
    supplier_id = serializers.IntegerField(source="supplier.id", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    items_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "invoice_id",
            "supplier_id",
            "supplier_name",
            "purchase_date",
            "created_at",
            "items_count",
        ]


class PurchaseDetailSerializer(serializers.ModelSerializer):
    supplier_id = serializers.IntegerField(source="supplier.id", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    items = PurchaseItemSerializer(many=True, read_only=True)

    class Meta:
        model = Purchase
        fields = [
            "id",
            "invoice_id",
            "supplier_id",
            "supplier_name",
            "purchase_date",
            "note",
            "created_at",
            "created_by",
            "items",
        ]
        read_only_fields = ["id", "created_at", "created_by", "items"]


class PurchaseSerializer(PurchaseDetailSerializer):
    pass


# ==========================================================
# CREATE serializers (INPUT)
# ==========================================================
class PurchaseCreateItemInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    cost_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    expired_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_expired_date(self, v):
        if v is None:
            return None
        v = str(v).strip()
        if not v or v == "—":
            return None
        d = parse_date(v)
        if not d:
            raise serializers.ValidationError("expired_date must be YYYY-MM-DD or null")
        return d


class PurchaseCreateSerializer(serializers.Serializer):
    supplier = serializers.IntegerField(required=False, allow_null=True)
    invoice_id = serializers.CharField(required=False, allow_blank=True, default="")
    purchase_date = serializers.DateField(required=False, allow_null=True)  # ✅ lebih aman
    note = serializers.CharField(required=False, allow_blank=True, default="")

    items = PurchaseCreateItemInputSerializer(many=True)

    def validate_supplier(self, v):
        if v is None:
            return None
        if not Supplier.objects.filter(pk=v).exists():
            raise serializers.ValidationError("Supplier not found")
        return v

    @transaction.atomic
    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        supplier_id = validated_data.get("supplier", None)
        invoice_id = (validated_data.get("invoice_id") or "").strip()
        note = (validated_data.get("note") or "").strip()

        purchase_date = validated_data.get("purchase_date")  # date or None
        pd = purchase_date or timezone.localdate()

        items_in = validated_data.get("items") or []
        if not items_in:
            raise serializers.ValidationError({"items": "At least 1 item is required"})

        purchase = Purchase.objects.create(
            supplier_id=supplier_id,
            invoice_id=invoice_id,
            note=note,
            created_by=user if user and user.is_authenticated else None,
            purchase_date=pd,
        )

        # Merge same product + expired + cost
        merged = {}
        for it in items_in:
            pid = int(it["product"])
            exp = it.get("expired_date", None)  # date or None
            cost = it["cost_price"]
            qty = int(it["quantity"])

            if not Product.objects.filter(pk=pid).exists():
                raise serializers.ValidationError({"items": f"Product {pid} not found"})

            key = (pid, exp, str(cost))
            merged.setdefault(
                key,
                {"product_id": pid, "expired_date": exp, "cost_price": cost, "quantity": 0},
            )
            merged[key]["quantity"] += qty

        # Create items + update stock + movement
        for _, row in merged.items():
            product = Product.objects.select_for_update().get(pk=row["product_id"])

            before = int(product.stock or 0)
            delta = int(row["quantity"])  # IN
            after = before + delta

            PurchaseItem.objects.create(
                purchase=purchase,
                product=product,
                quantity=delta,
                cost_price=row["cost_price"],
                expired_date=row["expired_date"],
            )

            product.stock = after
            product.save(update_fields=["stock"])

            StockMovement.objects.create(
                product=product,
                movement_type=StockMovement.Type.PURCHASE,
                quantity_delta=delta,
                before_stock=before,
                after_stock=after,
                note=f"Purchase #{purchase.id}",
                ref_model="Purchase",
                ref_id=purchase.id,
                created_by=purchase.created_by,
            )

        return purchase