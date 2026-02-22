from rest_framework import serializers
from pos.models_shift import Shift

class ShiftSerializer(serializers.ModelSerializer):
    cashier_name = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = [
            "id", "shop", "cashier", "cashier_name", "status",
            "opened_at", "closed_at",
            "opening_cash", "closing_cash",
            "total_sales", "total_refunds", "total_expenses",
            "expected_cash", "cash_difference",
            "note",
        ]
        read_only_fields = [
            "id", "cashier", "cashier_name", "status",
            "opened_at", "closed_at",
            "total_sales", "total_refunds", "total_expenses",
            "expected_cash", "cash_difference",
        ]

    def get_cashier_name(self, obj):
        u = obj.cashier
        return getattr(u, "display_name", None) or getattr(u, "full_name", None) or getattr(u, "username", "")