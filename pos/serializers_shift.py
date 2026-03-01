from rest_framework import serializers
from pos.models_shift import Shift


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = "__all__"


class ShiftOpenSerializer(serializers.Serializer):
    shop = serializers.IntegerField()
    opening_cash = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)


class ShiftCloseSerializer(serializers.Serializer):
    closing_cash = serializers.DecimalField(max_digits=12, decimal_places=2)