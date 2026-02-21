from decimal import Decimal
from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.db.models import DecimalField, ExpressionWrapper, Value
from pos.models import Order, OrderItem, Expense, Product, StockMovement

def money(v) -> str:
    if v is None:
        v = Decimal("0")
    try:
        v = Decimal(v)
    except Exception:
        v = Decimal("0")
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


def sales_summary(dr):
    qs = _paid_orders_qs(dr)

    agg = qs.aggregate(
        orders=Count("id"),
        net_sales=Coalesce(Sum("total"), 0),   # ✅ total adalah net sales kamu
        subtotal=Coalesce(Sum("subtotal"), 0),
        tax=Coalesce(Sum("tax"), 0),
        discount=Coalesce(Sum("discount"), 0),
        delivery_fee=Coalesce(Sum("delivery_fee"), 0),
    )

    orders = int(agg["orders"] or 0)
    net_sales = Decimal(agg["net_sales"] or 0)
    aov = (net_sales / orders) if orders > 0 else Decimal("0")

    return {
        "orders": orders,
        "net_sales": net_sales,
        "aov": aov,
        "subtotal": Decimal(agg["subtotal"] or 0),
        "tax": Decimal(agg["tax"] or 0),
        "discount": Decimal(agg["discount"] or 0),
        "delivery_fee": Decimal(agg["delivery_fee"] or 0),
    }


def orders_kpi(dr):
    return sales_summary(dr)


def expense_summary(dr):
    """
    ✅ Pastikan model Expense punya:
    - created_at (atau date)
    - amount
    - name
    Kalau berbeda, kirim field list Expense nanti saya sesuaikan.
    """
    qs = Expense.objects.filter(
        created_at__gte=dr.start,
        created_at__lt=dr.end,
    )

    total = qs.aggregate(total=Coalesce(Sum("amount"), 0))["total"] or 0

    top = (
        qs.values("name")
        .annotate(total=Coalesce(Sum("amount"), 0))
        .order_by("-total")[:5]
    )

    return {
        "total": Decimal(total),
        "top": [{"name": x["name"], "amount": Decimal(x["total"])} for x in top]
    }


def profit_summary(dr):
    s = sales_summary(dr)
    e = expense_summary(dr)
    profit = Decimal(s["net_sales"]) - Decimal(e["total"])
    return {
        "net_sales": Decimal(s["net_sales"]),
        "expense": Decimal(e["total"]),
        "profit": profit,
        "orders": s["orders"],
        "aov": s["aov"],
    }


def top_products(dr):
    """
    ✅ OrderItem fields kamu:
    - quantity (Integer)
    - price (Decimal)
    Revenue = Sum(quantity * price) (Decimal)
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
            qty=Coalesce(Sum("quantity"), 0),
            revenue=Coalesce(
                Sum(revenue_expr),
                Value(0, output_field=DecimalField(max_digits=18, decimal_places=2))
            ),
        )
        .order_by("-qty")[:5]
    )

    return [
        {
            "product_id": x["product_id"],
            "name": x["product__name"],
            "qty": int(x["qty"] or 0),
            "revenue": Decimal(x["revenue"] or 0),
        }
        for x in items
    ]


def stock_alert():
    qs = Product.objects.filter(stock__lt=F("min_stock")).order_by("stock")[:50]
    return [{"id": p.id, "name": p.name, "stock": p.stock, "min_stock": p.min_stock} for p in qs]


def stock_out():
    qs = Product.objects.filter(stock__lte=0).order_by("stock")[:50]
    return [{"id": p.id, "name": p.name, "stock": p.stock, "min_stock": p.min_stock} for p in qs]


def stock_item_by_name(name: str):
    qs = Product.objects.filter(name__icontains=name).order_by("name")[:10]
    return [{"id": p.id, "name": p.name, "stock": p.stock, "min_stock": p.min_stock} for p in qs]


def inventory_movement(dr):
    qs = StockMovement.objects.filter(created_at__gte=dr.start, created_at__lt=dr.end)

    by_type = (
        qs.values("movement_type")
        .annotate(count=Count("id"), qty=Coalesce(Sum("quantity_delta"), 0))
        .order_by("-count")
    )

    recent = qs.order_by("-created_at")[:10]

    return {
        "by_type": [{"type": x["movement_type"], "count": int(x["count"]), "qty": int(x["qty"])} for x in by_type],
        "recent": [
            {
                "id": m.id,
                "at": m.created_at,
                "type": m.movement_type,
                "product": getattr(m, "product_name", None) or getattr(m.product, "name", ""),
                "delta": int(m.quantity_delta),
                "before": int(m.before_stock) if m.before_stock is not None else None,
                "after": int(m.after_stock) if m.after_stock is not None else None,
                "note": m.note or "",
            }
            for m in recent
        ],
    }