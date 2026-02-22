from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, Value, DecimalField
from django.utils import timezone

DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))

def _sum_or_zero(qs, field_name: str) -> Decimal:
    agg = qs.aggregate(s=Sum(field_name, default=DEC0))
    return agg["s"] or Decimal("0.00")

@transaction.atomic
def recompute_shift_totals(shift, OrderModel, order_total_field="total_amount"):
    """
    OrderModel: model transaksi penjualan Anda.
    order_total_field: field decimal total pada Order.
    """
    # hanya order sukses
    orders = OrderModel.objects.filter(
        shop_id=shift.shop_id,
        created_at__gte=shift.opened_at,
        created_at__lte=(shift.closed_at or timezone.now()),
        status__in=["PAID", "COMPLETED"],  # sesuaikan status Anda
    )

    total_sales = _sum_or_zero(orders, order_total_field)

    # optional: refund model jika ada, kalau tidak ya 0
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
        "total_sales", "total_refunds", "total_expenses",
        "expected_cash", "cash_difference"
    ])
    return shift