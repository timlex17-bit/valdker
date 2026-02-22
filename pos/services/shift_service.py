from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone

DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))


def _sum_or_zero(qs, field_name: str) -> Decimal:
    """
    Sum decimal field safely (returns Decimal 0.00 if null).
    """
    agg = qs.aggregate(s=Coalesce(Sum(field_name), DEC0))
    return agg["s"] or Decimal("0.00")


@transaction.atomic
def recompute_shift_totals(shift, OrderModel, order_total_field: str = "total"):
    """
    Compute shift totals based on your current Order model.

    Notes (based on your Order fields):
    - Order has NO shop/shop_id field -> do NOT filter by shop_id.
    - Order has is_paid boolean -> use is_paid=True as "successful orders".
    - Order has created_at -> filter by shift time window.
    """

    time_end = shift.closed_at or timezone.now()

    # ✅ only paid orders inside shift window
    orders = OrderModel.objects.filter(
        created_at__gte=shift.opened_at,
        created_at__lte=time_end,
        is_paid=True,
    )

    # ✅ total sales from Order.total (default) or another field if you pass it
    total_sales = _sum_or_zero(orders, order_total_field)

    # optional: refunds/expenses (keep 0 if not implemented yet)
    total_refunds = Decimal("0.00")
    total_expenses = Decimal("0.00")

    expected_cash = (shift.opening_cash or Decimal("0.00")) + total_sales - total_refunds - total_expenses

    shift.total_sales = total_sales
    shift.total_refunds = total_refunds
    shift.total_expenses = total_expenses
    shift.expected_cash = expected_cash

    if shift.status == "CLOSED" and shift.closing_cash is not None:
        shift.cash_difference = (shift.closing_cash or Decimal("0.00")) - expected_cash
    else:
        shift.cash_difference = Decimal("0.00")

    shift.save(update_fields=[
        "total_sales",
        "total_refunds",
        "total_expenses",
        "expected_cash",
        "cash_difference",
    ])
    return shift