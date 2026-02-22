from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from pos.models_shift import Shift, ShiftStatus
from pos.api.serializers_shift import ShiftSerializer
from pos.services.shift_service import recompute_shift_totals

# ✅ GANTI ini ke model order Anda
from pos.models import Order  # <-- kalau nama beda: Sale/Transaction dll

ORDER_TOTAL_FIELD = "total_amount"  # <-- ganti jika field Anda grand_total/net_total/dll

def get_user_shop_id(request):
    """
    Sesuaikan dengan struktur Anda:
    - kalau user punya shop_id langsung
    - atau pakai StoreProfile aktif
    """
    # contoh umum:
    if hasattr(request.user, "shop_id") and request.user.shop_id:
        return request.user.shop_id
    # fallback: kirim dari header atau query, tapi sebaiknya user punya shop_id
    return request.headers.get("X-SHOP-ID")

class ShiftCurrentView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop_id = get_user_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        shift = Shift.objects.filter(shop_id=shop_id, cashier=request.user, status=ShiftStatus.OPEN).first()
        if not shift:
            return Response({"open": False, "shift": None}, status=200)

        # refresh totals realtime (optional)
        recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)

        return Response({"open": True, "shift": ShiftSerializer(shift).data}, status=200)

class ShiftOpenView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shop_id = get_user_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        opening_cash = request.data.get("opening_cash", "0")
        note = (request.data.get("note") or "").strip()

        try:
            opening_cash = Decimal(str(opening_cash))
        except Exception:
            return Response({"detail": "opening_cash tidak valid."}, status=400)

        # block jika masih ada shift open
        existing = Shift.objects.filter(shop_id=shop_id, cashier=request.user, status=ShiftStatus.OPEN).first()
        if existing:
            return Response({"detail": "Shift masih OPEN.", "shift": ShiftSerializer(existing).data}, status=409)

        shift = Shift.objects.create(
            shop_id=shop_id,
            cashier=request.user,
            status=ShiftStatus.OPEN,
            opening_cash=opening_cash,
            note=note,
        )

        # init totals
        recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)

        return Response({"detail": "Shift opened.", "shift": ShiftSerializer(shift).data}, status=201)

class ShiftCloseView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        shop_id = get_user_shop_id(request)
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

        shift = Shift.objects.filter(shop_id=shop_id, cashier=request.user, status=ShiftStatus.OPEN).first()
        if not shift:
            return Response({"detail": "Tidak ada shift OPEN."}, status=404)

        shift.status = ShiftStatus.CLOSED
        shift.closed_at = timezone.now()
        shift.closing_cash = closing_cash
        if note:
            shift.note = note
        shift.save(update_fields=["status", "closed_at", "closing_cash", "note"])

        recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)

        return Response({"detail": "Shift closed.", "shift": ShiftSerializer(shift).data}, status=200)

class ShiftListView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        shop_id = get_user_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        qs = Shift.objects.filter(shop_id=shop_id).select_related("cashier")[:200]
        return Response(ShiftSerializer(qs, many=True).data, status=200)

class ShiftReportView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        shop_id = get_user_shop_id(request)
        if not shop_id:
            return Response({"detail": "shop_id tidak ditemukan."}, status=400)

        shift = Shift.objects.filter(shop_id=shop_id, pk=pk).first()
        if not shift:
            return Response({"detail": "Shift tidak ditemukan."}, status=404)

        recompute_shift_totals(shift, OrderModel=Order, order_total_field=ORDER_TOTAL_FIELD)

        return Response({"shift": ShiftSerializer(shift).data}, status=200)