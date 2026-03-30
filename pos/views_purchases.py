from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Purchase
from .serializers_purchases import (
    PurchaseCreateSerializer,
    PurchaseListSerializer,
    PurchaseDetailSerializer,
)


def _role_ok(user):
    r = (getattr(user, "role", "") or "").lower().strip()
    return r in ["owner", "manager"] or getattr(user, "is_superuser", False)


def _user_shop(user):
    return getattr(user, "shop", None)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def purchases_list_create(request):
    if not _role_ok(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "GET":
        qs = (
            Purchase.objects
            .select_related("supplier")
            .prefetch_related("items", "items__product")
            .all()
        )

        if request.user.is_superuser:
            pass
        else:
            if not _user_shop(request.user):
                return Response({"detail": "No shop assigned."}, status=status.HTTP_400_BAD_REQUEST)
            qs = qs.filter(shop=_user_shop(request.user))

        ser = PurchaseListSerializer(qs, many=True)
        return Response(ser.data)

    ser = PurchaseCreateSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    p = ser.save()

    p = (
        Purchase.objects
        .select_related("supplier")
        .prefetch_related("items", "items__product")
        .get(pk=p.pk)
    )

    return Response(PurchaseDetailSerializer(p).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def purchases_detail(request, pk: int):
    if not _role_ok(request.user):
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    qs = (
        Purchase.objects
        .select_related("supplier")
        .prefetch_related("items", "items__product")
        .all()
    )

    if request.user.is_superuser:
        pass
    else:
        if not _user_shop(request.user):
            return Response({"detail": "No shop assigned."}, status=status.HTTP_400_BAD_REQUEST)
        qs = qs.filter(shop=_user_shop(request.user))

    try:
        p = qs.get(pk=pk)
    except Purchase.DoesNotExist:
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(PurchaseDetailSerializer(p).data)