from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from pos.models_shift import Shift, ShiftStatus
from .serializers_shift import ShiftSerializer, ShiftOpenSerializer, ShiftCloseSerializer


def _role(user) -> str:
    return (getattr(user, "role", "") or "").lower().strip()


def _is_admin_or_manager(user) -> bool:
    return getattr(user, "is_superuser", False) or _role(user) in ["admin", "manager"]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def shifts_list(request):
    """
    GET /api/shifts/
    - admin/manager: lihat semua
    - cashier: lihat shift miliknya saja
    """
    qs = Shift.objects.all().select_related("shop", "cashier").order_by("-opened_at", "-id")
    if not _is_admin_or_manager(request.user):
        qs = qs.filter(cashier=request.user)
    return Response(ShiftSerializer(qs, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def shifts_open(request):
    """
    POST /api/shifts/open/
    body: { "shop": 1, "opening_cash": "50.00" }
    """
    ser = ShiftOpenSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    shop_id = ser.validated_data["shop"]
    opening_cash = ser.validated_data.get("opening_cash") or 0

    # anti double open (per cashier)
    existing = Shift.objects.select_for_update().filter(
        cashier=request.user,
        status=ShiftStatus.OPEN,
    ).first()
    if existing:
        return Response(
            {"detail": "Shift already open", "shift_id": existing.id},
            status=status.HTTP_400_BAD_REQUEST,
        )

    shift = Shift.objects.create(
        shop_id=shop_id,
        cashier=request.user,
        opening_cash=opening_cash,
        status=ShiftStatus.OPEN,
    )
    return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def shifts_close(request, pk: int):
    """
    POST /api/shifts/<id>/close/
    body: { "closing_cash": "120.00" }
    """
    try:
        shift = Shift.objects.select_for_update().get(pk=pk)
    except Shift.DoesNotExist:
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    # cashier hanya boleh close shift sendiri
    if not _is_admin_or_manager(request.user) and shift.cashier_id != request.user.id:
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    if shift.status != ShiftStatus.OPEN:
        return Response({"detail": "Shift is not open"}, status=status.HTTP_400_BAD_REQUEST)

    ser = ShiftCloseSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    shift.closing_cash = ser.validated_data["closing_cash"]
    shift.status = ShiftStatus.CLOSED
    shift.save(update_fields=["closing_cash", "status"])

    shift.refresh_from_db()
    return Response(ShiftSerializer(shift).data, status=status.HTTP_200_OK)