from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Purchase
from .serializers_purchases import PurchaseCreateSerializer, PurchaseListSerializer, PurchaseDetailSerializer


def _role_ok(user):
    r = (getattr(user, "role", "") or "").lower().strip()
    return r in ["admin", "manager"] or getattr(user, "is_superuser", False)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def purchases_list_create(request):
    # admin/manager only
    if not _role_ok(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "GET":
        qs = Purchase.objects.prefetch_related("items", "supplier").all()
        ser = PurchaseListSerializer(qs, many=True)
        return Response(ser.data)

    # POST
    ser = PurchaseCreateSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    p = ser.save()

    # return detail-ish data
    out = PurchaseDetailSerializer(p).data
    return Response(out, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def purchases_detail(request, pk: int):
    if not _role_ok(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    try:
        p = Purchase.objects.prefetch_related("items", "supplier").get(pk=pk)
    except Purchase.DoesNotExist:
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(PurchaseDetailSerializer(p).data)