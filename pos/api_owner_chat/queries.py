from decimal import Decimal
from django.db.models import (
    Sum, Count, F, DecimalField, ExpressionWrapper, Value, IntegerField
)
from django.db.models.functions import Coalesce, ExtractHour

from pos.models import Order, OrderItem, Expense, Product, StockMovement


DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))
INT0 = Value(0, output_field=IntegerField())


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


def _filter_shop(qs, shop):
    if shop is None:
        return qs
    return qs.filter(shop=shop)


def _paid_orders_qs(dr, shop=None):
    qs = Order.objects.filter(
        created_at__gte=dr.start,
        created_at__lt=dr.end,
        is_paid=True
    )
    return _filter_shop(qs, shop)


def sales_summary(dr, shop=None):
    qs = _paid_orders_qs(dr, shop=shop)

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


def orders_kpi(dr, shop=None):
    return sales_summary(dr, shop=shop)


def expense_summary(dr, shop=None):
    start_date = dr.start.date()
    end_date = dr.end.date()

    qs = Expense.objects.filter(date__gte=start_date, date__lt=end_date)
    qs = _filter_shop(qs, shop)

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


def profit_summary(dr, shop=None):
    s = sales_summary(dr, shop=shop)
    e = expense_summary(dr, shop=shop)

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


def top_products(dr, shop=None):
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
    )

    if shop is not None:
        items = items.filter(order__shop=shop)

    items = (
        items.values("product_id", "product__name")
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


def stock_alert(shop=None, threshold: int = 5):
    qs = Product.objects.filter(stock__lte=threshold)
    qs = _filter_shop(qs, shop)
    qs = qs.order_by("stock", "name")[:50]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": threshold} for p in qs]


def stock_threshold(threshold: int, shop=None):
    return stock_alert(shop=shop, threshold=threshold)


def stock_out(shop=None):
    qs = Product.objects.filter(stock__lte=0)
    qs = _filter_shop(qs, shop)
    qs = qs.order_by("stock", "name")[:50]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0), "min_stock": 0} for p in qs]


def stock_item_by_name(name: str, shop=None):
    qs = Product.objects.filter(name__icontains=name)
    qs = _filter_shop(qs, shop)
    qs = qs.order_by("name")[:10]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0)} for p in qs]


def inventory_movement(dr, shop=None):
    qs = StockMovement.objects.filter(created_at__gte=dr.start, created_at__lt=dr.end)
    qs = _filter_shop(qs, shop)

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


def margin_summary(dr, shop=None):
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

    if shop is not None:
        qs = qs.filter(order__shop=shop)

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


def high_stock_products(limit=5, shop=None):
    qs = Product.objects.all()
    qs = _filter_shop(qs, shop)
    qs = qs.order_by("-stock", "name")[:limit]
    return [{"id": p.id, "name": p.name, "stock": int(p.stock or 0)} for p in qs]


class QueryService:
    def __init__(self, shop):
        self.shop = shop

    def sales_summary(self, dr):
        return sales_summary(dr, shop=self.shop)

    def profit_summary(self, dr):
        return profit_summary(dr, shop=self.shop)

    def margin_summary(self, dr):
        return margin_summary(dr, shop=self.shop)

    def top_products(self, dr):
        return top_products(dr, shop=self.shop)

    def high_stock_products(self, limit=5):
        return high_stock_products(limit=limit, shop=self.shop)


def for_shop(shop):
    return QueryService(shop)