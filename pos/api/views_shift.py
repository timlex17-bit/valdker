# pos/api/views_shift.py
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from pos.models_shift import Shift, ShiftStatus
from pos.api.serializers_shift import ShiftSerializer
from pos.services.shift_service import recompute_shift_totals

# ✅ ganti kalau field total order beda: total_amount / grand_total / net_total
ORDER_TOTAL_FIELD = "total"


def resolve_shop_id(request) -> Optional[int]:
    """
    Sumber shop_id:
    1) query ?shop_id=1
    2) request.user.shop_id (kalau ada)
    3) fallback: Shop pertama
    """
    q = request.query_params.get("shop_id")
    if q:
        try:
            return int(q)
        except ValueError:
            pass

    if hasattr(request.user, "shop_id") and getattr(request.user, "shop_id", None):
        try:
            return int(request.user.shop_id)
        except Exception:
            pass

    # ✅ lazy import biar kalau Shop model beda file, errornya jelas di runtime
    from pos.models import Shop

    shop = Shop.objects.order_by("id").first()
    return int(shop.id) if shop else None


def find_open_shift(shop_id: int):
    return (
        Shift.objects
        .filter(shop_id=shop_id, status=ShiftStatus.OPEN, closed_at__isnull=True)
        .order_by("-opened_at", "-id")
        .first()
    )


class ShiftCurrentView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        shift = find_open_shift(shop_id)
        if not shift:
            return Response({"open": False, "shift": None, "shop_id": shop_id}, status=200)

        # ✅ lazy import Order juga (menghindari import crash)
        from pos.models import Order

        try:
            recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)
        except Exception as e:
            # biar kalau field total salah, kamu dapat error JSON bukan HTML
            return Response(
                {"detail": "Error recompute_shift_totals", "error": str(e), "shop_id": shop_id},
                status=500
            )

        return Response({"open": True, "shift": ShiftSerializer(shift).data, "shop_id": shop_id}, status=200)


class ShiftOpenView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        opening_cash = request.data.get("opening_cash", "0")
        note = (request.data.get("note") or "").strip()

        try:
            opening_cash = Decimal(str(opening_cash))
        except Exception:
            return Response({"detail": "opening_cash tidak valid."}, status=400)

        existing = find_open_shift(shop_id)
        if existing:
            return Response(
                {"detail": "Shift masih OPEN.", "shift": ShiftSerializer(existing).data, "shop_id": shop_id},
                status=409
            )

        shift = Shift.objects.create(
            shop_id=shop_id,
            cashier=request.user,
            status=ShiftStatus.OPEN,
            opened_at=timezone.now(),
            closed_at=None,            
            closing_cash=None,         
            opening_cash=opening_cash,
            note=note,
        )

        from pos.models import Order
        try:
            recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)
        except Exception as e:
            return Response({"detail": "Error recompute_shift_totals", "error": str(e)}, status=500)

        return Response({"detail": "Shift opened.", "shift": ShiftSerializer(shift).data, "shop_id": shop_id}, status=201)


class ShiftCloseView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        closing_cash = request.data.get("closing_cash", None)
        note = (request.data.get("note") or "").strip()

        if closing_cash is None:
            return Response({"detail": "closing_cash wajib."}, status=400)

        try:
            closing_cash = Decimal(str(closing_cash))
        except Exception:
            return Response({"detail": "closing_cash tidak valid."}, status=400)

        shift = find_open_shift(shop_id)
        if not shift:
            return Response({"detail": "Tidak ada shift OPEN.", "shop_id": shop_id}, status=404)

        shift.status = ShiftStatus.CLOSED
        shift.closed_at = timezone.now()
        shift.closing_cash = closing_cash
        if note:
            shift.note = note
        shift.save(update_fields=["status", "closed_at", "closing_cash", "note"])

        from pos.models import Order
        try:
            recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)
        except Exception as e:
            return Response({"detail": "Error recompute_shift_totals", "error": str(e)}, status=500)

        return Response({"detail": "Shift closed.", "shift": ShiftSerializer(shift).data, "shop_id": shop_id}, status=200)


class ShiftListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        qs = (
            Shift.objects
            .filter(shop_id=shop_id)
            .select_related("cashier")
            .order_by("-opened_at", "-id")[:200]
        )
        return Response(ShiftSerializer(qs, many=True).data, status=200)


class ShiftReportView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        shop_id = resolve_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        shift = Shift.objects.filter(shop_id=shop_id, pk=pk).first()
        if not shift:
            return Response({"detail": "Shift tidak ditemukan."}, status=404)

        from pos.models import Order
        try:
            recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)
        except Exception as e:
            return Response({"detail": "Error recompute_shift_totals", "error": str(e)}, status=500)

        return Response({"shift": ShiftSerializer(shift).data, "shop_id": shop_id}, status=200)