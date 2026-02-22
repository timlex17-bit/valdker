from decimal import Decimal
from django.utils import timezone
from pos.models_shift import Shift


def get_opening_cash_today(shop_id, user=None):
    today = timezone.localdate()
    qs = Shift.objects.filter(
        shop_id=shop_id,
        opened_at__date=today,
    ).order_by("-opened_at")

    if user is not None:
        qs = qs.filter(cashier=user)

    s = qs.first()
    return (s.opening_cash if s else Decimal("0.00")), (s.id if s else None)