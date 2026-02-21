from decimal import Decimal
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper, Value, IntegerField
from django.db.models.functions import Coalesce

from pos.models import Order, OrderItem, Expense, Product, StockMovement


# =========================================================
# CONSTANTS
# =========================================================
DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))
INT0 = Value(0, output_field=IntegerField())


# =========================================================
# HELPERS
# =========================================================
def _to_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0.00")
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0.00")


def money(v) -> str:
    v = _to_decimal(v)
    return f"${v:,.2f}"


def _paid_orders_qs(dr):
    """
    ✅ Cocok dengan model Order kamu:
    - created_at: datetime
    - is_paid: boolean
    """
    return Order.objects.filter(
        created_at__gte=dr.start,
        created_at__lt=dr.end,
        is_paid=True
    )


# =========================================================
# SALES / INCOME
# =========================================================
def sales_summary(dr):
    qs = _paid_orders_qs(dr)

    agg = qs.aggregate(
        orders=Count("id"),
        net_sales=Coalesce(Sum("total"), DEC0),
        subtotal=Coalesce(Sum("subtotal"), DEC0),
        tax=Coalesce(Sum("tax"), DEC0),
        discount=Coalesce(Sum("discount"), DEC0),
        delivery_fee=Coalesce(Sum("delivery_fee"), DEC0),
    )

    orders = int(agg.get("orders") or 0)
    net_sales = _to_decimal(agg.get("net_sales"))
    aov = (net_sales / Decimal(str(orders))) if orders > 0 else Decimal("0.00")

    return {
        "orders": orders,
        "net_sales": net_sales,
        "aov": aov,
        "subtotal": _to_decimal(agg.get("subtotal")),
        "tax": _to_decimal(agg.get("tax")),
        "discount": _to_decimal(agg.get("discount")),
        "delivery_fee": _to_decimal(agg.get("delivery_fee")),
    }


def orders_kpi(dr):
    return sales_summary(dr)


# =========================================================
# EXPENSE (IMPORTANT: Expense model has date+time, NO created_at)
# =========================================================
def expense_summary(dr):
    """
    ✅ Expense fields:
    - amount (Decimal)
    - date (DateField)
    - time (TimeField)
    """
    start_date = dr.start.date()
    end_date = dr.end.date()  # end is exclusive

    qs = Expense.objects.filter(
        date__gte=start_date,
        date__lt=end_date,
    )

    total = qs.aggregate(total=Coalesce(Sum("amount"), DEC0)).get("total")

    top_qs = (
        qs.values("name")
        .annotate(amount=Coalesce(Sum("amount"), DEC0))
        .order_by("-amount")[:5]
    )

    return {
        "total": _to_decimal(total),
        "top": [{"name": x["name"], "amount": _to_decimal(x["amount"])} for x in top_qs]
    }


# =========================================================
# PROFIT (Net Sales - Expense)
# =========================================================
def profit_summary(dr):
    s = sales_summary(dr)
    e = expense_summary(dr)

    net_sales = _to_decimal(s.get("net_sales"))
    expense = _to_decimal(e.get("total"))
    profit = net_sales - expense

    return {
        "net_sales": net_sales,
        "expense": expense,
        "profit": profit,
        "orders": int(s.get("orders") or 0),
        "aov": _to_decimal(s.get("aov")),
    }


# =========================================================
# TOP PRODUCTS
# =========================================================
def top_products(dr):
    """
    ✅ OrderItem fields:
    - quantity (PositiveInteger)
    - price (Decimal)
    Revenue = Sum(quantity * price)
    """
    revenue_expr = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=18, decimal_places=2)
    )

    items = (
        OrderItem.objects
        .filter(
            order__created_at__gte=dr.start,
            order__created_at__lt=dr.end,
            order__is_paid=True
        )
        .values("product_id", "product__name")
        .annotate(
            qty=Coalesce(Sum("quantity"), INT0),
            revenue=Coalesce(Sum(revenue_expr), DEC0),
        )
        .order_by("-qty")[:5]
    )

    return [
        {
            "product_id": x["product_id"],
            "name": x["product__name"],
            "qty": int(x["qty"] or 0),
            "revenue": _to_decimal(x["revenue"]),
        }
        for x in items
    ]


# =========================================================
# STOCK ALERTS
# =========================================================
def stock_alert(threshold: int = 5):
    """
    Karena Product model kamu belum punya min_stock,
    maka "stok menipis" pakai threshold default.

    ✅ default: stock <= 5
    """
    qs = (
        Product.objects
        .filter(stock__lte=threshold)
        .order_by("stock", "name")[:50]
    )

    return [
        {"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": threshold}
        for p in qs
    ]


def stock_out():
    qs = Product.objects.filter(stock__lte=0).order_by("stock", "name")[:50]
    return [
        {"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": 0}
        for p in qs
    ]


def stock_item_by_name(name: str):
    qs = Product.objects.filter(name__icontains=name).order_by("name")[:10]
    return [
        {"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": None}
        for p in qs
    ]


# =========================================================
# INVENTORY MOVEMENT
# =========================================================
def inventory_movement(dr):
    qs = StockMovement.objects.filter(created_at__gte=dr.start, created_at__lt=dr.end)

    by_type = (
        qs.values("movement_type")
        .annotate(count=Count("id"), qty=Coalesce(Sum("quantity_delta"), INT0))
        .order_by("-count")
    )

    recent = qs.order_by("-created_at")[:10]

    return {
        "by_type": [
            {"type": x["movement_type"], "count": int(x["count"] or 0), "qty": int(x["qty"] or 0)}
            for x in by_type
        ],
        "recent": [
            {
                "id": m.id,
                "at": m.created_at,
                "type": m.movement_type,
                "product": getattr(m.product, "name", ""),
                "delta": int(m.quantity_delta or 0),
                "before": int(m.before_stock) if m.before_stock is not None else None,
                "after": int(m.after_stock) if m.after_stock is not None else None,
                "note": m.note or "",
            }
            for m in recent
        ],
    }