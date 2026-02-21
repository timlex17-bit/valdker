from decimal import Decimal
from django.db.models import (
    Sum, Count, F, DecimalField, ExpressionWrapper, Value, IntegerField
)
from django.db.models.functions import Coalesce, ExtractHour

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
    return Order.objects.filter(
        created_at__gte=dr.start,
        created_at__lt=dr.end,
        is_paid=True
    )


# =========================================================
# CORE KPI
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


def expense_summary(dr):
    """
    Expense model: date + time (NO created_at)
    """
    start_date = dr.start.date()
    end_date = dr.end.date()  # end exclusive

    qs = Expense.objects.filter(date__gte=start_date, date__lt=end_date)

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
# LEVEL 1 — SALES ANALYTICS
# =========================================================
def sales_by_order_type(dr):
    qs = _paid_orders_qs(dr)

    rows = (
        qs.values("default_order_type")
        .annotate(
            orders=Count("id"),
            total=Coalesce(Sum("total"), DEC0),
            discount=Coalesce(Sum("discount"), DEC0),
            delivery_fee=Coalesce(Sum("delivery_fee"), DEC0),
        )
        .order_by("-total")
    )

    return [
        {
            "order_type": r["default_order_type"],
            "orders": int(r["orders"] or 0),
            "total": _to_decimal(r["total"]),
            "discount": _to_decimal(r["discount"]),
            "delivery_fee": _to_decimal(r["delivery_fee"]),
        }
        for r in rows
    ]


def sales_by_type(dr, order_type: str):
    """
    Filter by a single order type.
    order_type must match Order.OrderType values: GENERAL/DINE_IN/TAKE_OUT/DELIVERY
    """
    qs = _paid_orders_qs(dr).filter(default_order_type=order_type)
    agg = qs.aggregate(
        orders=Count("id"),
        total=Coalesce(Sum("total"), DEC0),
        discount=Coalesce(Sum("discount"), DEC0),
        delivery_fee=Coalesce(Sum("delivery_fee"), DEC0),
    )
    return {
        "order_type": order_type,
        "orders": int(agg["orders"] or 0),
        "total": _to_decimal(agg["total"]),
        "discount": _to_decimal(agg["discount"]),
        "delivery_fee": _to_decimal(agg["delivery_fee"]),
    }


def delivery_fee_summary(dr):
    qs = _paid_orders_qs(dr)
    agg = qs.aggregate(delivery_fee=Coalesce(Sum("delivery_fee"), DEC0))
    return {"delivery_fee": _to_decimal(agg["delivery_fee"])}


def discount_summary(dr):
    qs = _paid_orders_qs(dr)
    agg = qs.aggregate(discount=Coalesce(Sum("discount"), DEC0))
    return {"discount": _to_decimal(agg["discount"])}


def payment_method_top(dr, limit=5):
    qs = _paid_orders_qs(dr)
    rows = (
        qs.values("payment_method")
        .annotate(
            orders=Count("id"),
            total=Coalesce(Sum("total"), DEC0),
        )
        .order_by("-orders", "-total")[:limit]
    )
    return [
        {"method": (r["payment_method"] or "-"), "orders": int(r["orders"] or 0), "total": _to_decimal(r["total"])}
        for r in rows
    ]


def cash_vs_transfer(dr):
    """
    Classify payment_method into buckets.
    Adjust keywords based on your POS options.
    """
    qs = _paid_orders_qs(dr)

    cash_kw = ("cash", "tunai")
    transfer_kw = ("transfer", "bank", "bnctl", "bnu", "mandiri")
    qris_kw = ("qris",)

    def bucket(method: str) -> str:
        m = (method or "").strip().lower()
        if any(k in m for k in cash_kw):
            return "CASH"
        if any(k in m for k in qris_kw):
            return "QRIS"
        if any(k in m for k in transfer_kw):
            return "TRANSFER"
        return "OTHER"

    rows = qs.values("payment_method").annotate(orders=Count("id"), total=Coalesce(Sum("total"), DEC0))

    out = {
        "CASH": {"orders": 0, "total": Decimal("0.00")},
        "TRANSFER": {"orders": 0, "total": Decimal("0.00")},
        "QRIS": {"orders": 0, "total": Decimal("0.00")},
        "OTHER": {"orders": 0, "total": Decimal("0.00")},
    }

    for r in rows:
        b = bucket(r["payment_method"])
        out[b]["orders"] += int(r["orders"] or 0)
        out[b]["total"] += _to_decimal(r["total"])

    return out


def busiest_hours(dr, limit=5):
    qs = _paid_orders_qs(dr)
    rows = (
        qs.annotate(h=ExtractHour("created_at"))
        .values("h")
        .annotate(orders=Count("id"), total=Coalesce(Sum("total"), DEC0))
        .order_by("-orders", "-total")[:limit]
    )
    return [
        {"hour": int(r["h"] or 0), "orders": int(r["orders"] or 0), "total": _to_decimal(r["total"])}
        for r in rows
    ]


# =========================================================
# LEVEL 1 — INVENTORY ANALYTICS
# =========================================================
def top_products(dr):
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


def stock_alert(threshold: int = 5):
    qs = Product.objects.filter(stock__lte=threshold).order_by("stock", "name")[:50]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": threshold} for p in qs]


def stock_threshold(threshold: int):
    return stock_alert(threshold=threshold)


def stock_out():
    qs = Product.objects.filter(stock__lte=0).order_by("stock", "name")[:50]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": 0} for p in qs]


def stock_item_by_name(name: str):
    qs = Product.objects.filter(name__icontains=name).order_by("name")[:10]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0)} for p in qs]


def movement_by_type(dr, movement_type="ADJUSTMENT", limit=10):
    qs = StockMovement.objects.filter(
        created_at__gte=dr.start,
        created_at__lt=dr.end,
        movement_type=movement_type
    ).order_by("-created_at")[:limit]

    return [
        {
            "id": m.id,
            "at": m.created_at,
            "type": m.movement_type,
            "product": m.product.name,
            "delta": int(m.quantity_delta or 0),
            "note": m.note or "",
        }
        for m in qs
    ]


# =========================================================
# LEVEL 1 — FINANCE ANALYTICS (MARGIN)
# =========================================================
def margin_summary(dr):
    """
    Gross Margin approximation from OrderItem:
    revenue = sum(qty * sell_price_at_time(price))
    cost = sum(qty * current product.buy_price)
    """
    revenue_expr = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=18, decimal_places=2)
    )
    cost_expr = ExpressionWrapper(
        F("quantity") * F("product__buy_price"),
        output_field=DecimalField(max_digits=18, decimal_places=2)
    )

    qs = OrderItem.objects.filter(
        order__created_at__gte=dr.start,
        order__created_at__lt=dr.end,
        order__is_paid=True
    )

    agg = qs.aggregate(
        revenue=Coalesce(Sum(revenue_expr), DEC0),
        cost=Coalesce(Sum(cost_expr), DEC0),
        qty=Coalesce(Sum("quantity"), INT0),
    )

    revenue = _to_decimal(agg["revenue"])
    cost = _to_decimal(agg["cost"])
    gross_profit = revenue - cost
    margin_pct = (gross_profit / revenue * Decimal("100")) if revenue > 0 else Decimal("0.00")

    return {
        "revenue": revenue,
        "cost": cost,
        "gross_profit": gross_profit,
        "margin_pct": margin_pct
    }


def high_stock_products(limit=5):
    qs = Product.objects.order_by("-stock", "name")[:limit]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0)} for p in qs]


# =========================================================
# INVENTORY MOVEMENT (existing)
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