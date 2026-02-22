# pos/api/views_finance.py
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
    return [f.name for f in model._meta.fields]


def resolve_shop_id(request) -> int | None:
    """
    ✅ Fix utama:
    - Prioritas: query param shop_id (optional)
    - Lalu: request.user.shop_id jika ada
    - Fallback: Shop pertama di DB
    """
    # 0) optional override
    q = request.query_params.get("shop_id")
    if q:
        try:
            return int(q)
        except ValueError:
            pass

    # 1) user.shop_id (kalau kamu punya multi-tenant nanti)
    if hasattr(request.user, "shop_id") and request.user.shop_id:
        return request.user.shop_id

    # 2) fallback: shop pertama
    shop = Shop.objects.order_by("id").first()
    return shop.id if shop else None


def apply_shop_filter(qs, shop_id):
    if not shop_id:
        return qs

    if field_exists(Order, "shop"):
        return qs.filter(shop_id=shop_id)

    if field_exists(Order, "shop_id"):
        return qs.filter(shop_id=shop_id)

    for name in ["store", "outlet", "branch"]:
        if field_exists(Order, name):
            return qs.filter(**{f"{name}_id": shop_id})

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

        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({
                "detail": "Shop belum ada di database. Buat 1 Shop dulu."
            }, status=400)

        today = timezone.localdate()

        qs = Order.objects.all()
        qs = apply_shop_filter(qs, shop_id)

        date_field = pick_date_field()
        if not date_field:
            return Response({
                "detail": "Field tanggal Order tidak ditemukan.",
                "order_fields": list_model_fields(Order),
            }, status=500)

        qs = qs.filter(**{f"{date_field}__date": today})

        total_field = pick_total_field()
        if not total_field:
            return Response({
                "detail": "Field total Order tidak ditemukan.",
                "order_fields": list_model_fields(Order),
            }, status=500)

        total_sales = qs.aggregate(s=Sum(total_field, default=DEC0))["s"] or Decimal("0.00")
        order_count = qs.count()

        opening_cash, shift_id = get_opening_cash_today(shop_id)

        return Response({
            "range": "today",
            "from": str(today),
            "to": str(today),
            "total_sales_today": str(total_sales),
            "order_count_today": order_count,
            "shift_opening_cash": str(opening_cash),
            "shift_id": shift_id,
            "shop_id": shop_id,
        })