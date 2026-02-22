from decimal import Decimal

from django.utils import timezone
from django.db.models import Sum, Value, DecimalField
from django.core.exceptions import FieldDoesNotExist

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from pos.models import Order, Shop
from pos.services.finance_service import get_opening_cash_today

DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))


def field_exists(model, name: str) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return False


def list_model_fields(model):
    # only concrete fields (no reverse relations)
    return [f.name for f in model._meta.fields]


def get_shop_id_from_request(request):
    # ✅ opsi 1: user punya shop_id
    if hasattr(request.user, "shop_id") and request.user.shop_id:
        return request.user.shop_id

    # ✅ opsi 2: single shop fallback
    shop = Shop.objects.first()
    return shop.id if shop else None


def apply_shop_filter(qs, shop_id):
    """
    Coba beberapa kemungkinan nama field shop di Order.
    """
    if not shop_id:
        return qs

    # paling umum: shop (FK)
    if field_exists(Order, "shop"):
        return qs.filter(shop_id=shop_id)

    # kadang shop_id disimpan langsung sebagai int
    if field_exists(Order, "shop_id"):
        return qs.filter(shop_id=shop_id)

    # alternatif naming
    for name in ["store", "outlet", "branch"]:
        if field_exists(Order, name):
            return qs.filter(**{f"{name}_id": shop_id})

    # kalau tidak ada field shop sama sekali -> biarkan tanpa filter
    return qs


def pick_date_field():
    for name in ["created_at", "created", "date", "ordered_at", "order_date", "timestamp"]:
        if field_exists(Order, name):
            return name
    return None


def pick_total_field():
    for name in ["total", "grand_total", "total_price", "net_total", "amount", "final_total"]:
        if field_exists(Order, name):
            return name
    return None


class FinanceSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        range_ = (request.query_params.get("range") or "today").lower()
        if range_ != "today":
            range_ = "today"

        shop_id = get_shop_id_from_request(request)
        if not shop_id:
            return Response({"detail": "Shop tidak ditemukan."}, status=400)

        today = timezone.localdate()

        qs = Order.objects.all()
        qs = apply_shop_filter(qs, shop_id)

        date_field = pick_date_field()
        if not date_field:
            return Response({
                "detail": "Tidak menemukan field tanggal di Order (created_at/date/ordered_at, dll).",
                "order_fields": list_model_fields(Order),
            }, status=500)

        qs = qs.filter(**{f"{date_field}__date": today})

        total_field = pick_total_field()
        if not total_field:
            return Response({
                "detail": "Tidak menemukan field total di Order (total/grand_total/total_price, dll).",
                "order_fields": list_model_fields(Order),
            }, status=500)

        total_sales = qs.aggregate(s=Sum(total_field, default=DEC0))["s"] or Decimal("0.00")
        order_count = qs.count()

        opening_cash, shift_id = get_opening_cash_today(shop_id)

        return Response({
            "range": "today",
            "from": str(today),
            "to": str(today),

            # ✅ sales summary (optional)
            "total_sales_today": str(total_sales),
            "order_count_today": order_count,

            # ✅ SHIFT fields untuk Android Dashboard
            "shift_opening_cash": str(opening_cash),
            "shift_id": shift_id,
        })