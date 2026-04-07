import io
import os
import json
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Sum, Value, DecimalField, F, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, authentication_classes, action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from xhtml2pdf import pisa

from .decorators import role_required
from .models import (
    Order, OrderItem, Customer, Supplier, Product, Category, Unit, Banner, Shop, Expense,
    Purchase, StockAdjustment, InventoryCount, ProductReturn, StockMovement,
    PaymentMethod, BankAccount, SalePayment, BankLedger, CustomUser,
)
from .permissions import (
    IsPlatformAdminOnly,
    OwnerOnlyWriteOrRead,
    OwnerOrManagerWriteOrRead,
    IsOwnerOrManagerOrPlatformAdmin,
    BankAccountPermission,
    ShopStaffPermission,
)
from .serializers import (
    OrderSerializer, CustomerSerializer, SupplierSerializer,
    ProductSerializer, CategorySerializer, UnitSerializer, ShopSerializer,
    ExpenseSerializer, BannerSerializer,
    StockAdjustmentSerializer, InventoryCountSerializer, ProductReturnSerializer, StockMovementSerializer,
    PaymentMethodSerializer, BankAccountSerializer, SalePaymentSerializer, BankLedgerSerializer,
    StaffSerializer,
)
from .serializers_purchases import PurchaseSerializer, PurchaseCreateSerializer


# =========================
# Helpers
# =========================
def _admin_context(request, title: str):
    ctx = django_admin.site.each_context(request)
    ctx["title"] = title
    return ctx


def _render_with_fallback(request, templates, context):
    last_err = None
    for tpl in templates:
        try:
            return render(request, tpl, context)
        except TemplateDoesNotExist as e:
            last_err = e
            continue
    raise last_err


def _user_shop(request):
    return getattr(request.user, "shop", None)


def _require_user_shop(request):
    if request.user.is_superuser:
        raise ValidationError("Platform admin has no tenant shop context for this endpoint.")

    shop = _user_shop(request)
    if not shop:
        raise ValidationError("User tidak memiliki shop.")

    return shop


def _model_has_field(model, field_name: str) -> bool:
    return any(getattr(field, "name", None) == field_name for field in model._meta.get_fields())


def _shop_filter_or_all(request, qs, shop_field="shop"):
    """
    Untuk superuser: lihat semua data.
    Untuk user biasa: filter per shop.
    Jika user biasa tidak punya shop: none().
    """
    if request.user.is_superuser:
        return qs

    shop = _user_shop(request)
    if not shop:
        return qs.none()

    if shop_field == "shop":
        return qs.filter(shop=shop)

    return qs.filter(**{shop_field: shop})


def _tenant_queryset(request, model, **filters):
    """
    Helper queryset tenant-safe.
    - superuser: bisa lihat semua
    - user biasa tanpa shop: none()
    - user biasa dengan shop: filter(shop=user.shop)
    """
    if request.user.is_superuser:
        return model.objects.filter(**filters)

    shop = _user_shop(request)
    if not shop:
        return model.objects.none()

    return model.objects.filter(shop=shop, **filters)


class RequestContextMixin:
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx


class TenantModelViewSet(RequestContextMixin, viewsets.ModelViewSet):
    tenant_model = None
    tenant_ordering = ("-id",)

    def get_queryset(self):
        if self.tenant_model is None:
            raise AssertionError("tenant_model must be set")

        qs = _tenant_queryset(self.request, self.tenant_model)
        ordering = getattr(self, "tenant_ordering", None)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    def perform_create(self, serializer):
        if self.request.user.is_superuser:
            raise ValidationError("Platform admin cannot create tenant data from this endpoint.")

        shop = _require_user_shop(self.request)
        serializer.save(shop=shop)


class TenantReadOnlyModelViewSet(RequestContextMixin, viewsets.ReadOnlyModelViewSet):
    tenant_model = None
    tenant_ordering = ("-id",)

    def get_queryset(self):
        if self.tenant_model is None:
            raise AssertionError("tenant_model must be set")

        qs = _tenant_queryset(self.request, self.tenant_model)
        ordering = getattr(self, "tenant_ordering", None)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs


ORDER_TOTAL_FIELD = "total"
EXPENSE_AMOUNT_FIELD = "amount"


# =========================
# Profit APIs (owner / manager / platform admin)
# =========================
class DailyProfitReportAPIView(APIView):
    permission_classes = [IsOwnerOrManagerOrPlatformAdmin]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        today = timezone.localdate()
        if not end:
            end = today
        if not start:
            start = end - timedelta(days=13)

        sales_qs = (
            _shop_filter_or_all(
                request,
                Order.objects.filter(
                    is_paid=True,
                    created_at__date__gte=start,
                    created_at__date__lte=end
                )
            )
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(
                total=Coalesce(
                    Sum("total"),
                    Value(0),
                    output_field=DecimalField(max_digits=18, decimal_places=2)
                )
            )
            .order_by("d")
        )

        exp_qs = (
            _shop_filter_or_all(
                request,
                Expense.objects.filter(date__gte=start, date__lte=end)
            )
            .values("date")
            .annotate(
                total=Coalesce(
                    Sum("amount"),
                    Value(0),
                    output_field=DecimalField(max_digits=18, decimal_places=2)
                )
            )
            .order_by("date")
        )

        sales_map = {row["d"]: row["total"] for row in sales_qs}
        exp_map = {row["date"]: row["total"] for row in exp_qs}
        all_days = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

        rows = []
        total_sales = Decimal("0")
        total_exp = Decimal("0")

        for d in all_days:
            s = sales_map.get(d, Decimal("0"))
            e = exp_map.get(d, Decimal("0"))
            p = s - e
            total_sales += s
            total_exp += e

            rows.append({
                "date": d.isoformat(),
                "sales": float(s),
                "expense": float(e),
                "profit": float(p),
            })

        return Response({
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "summary": {
                "sales": float(total_sales),
                "expense": float(total_exp),
                "profit": float(total_sales - total_exp),
            },
            "rows": rows
        })


class MonthlyPLReportAPIView(APIView):
    permission_classes = [IsOwnerOrManagerOrPlatformAdmin]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        today = timezone.localdate()
        if not start:
            start = today.replace(day=1)
        if not end:
            end = today

        sales_qs = (
            _shop_filter_or_all(
                request,
                Order.objects.filter(
                    is_paid=True,
                    created_at__date__gte=start,
                    created_at__date__lte=end
                )
            )
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(total=Sum("total"))
            .order_by("d")
        )

        exp_qs = (
            _shop_filter_or_all(
                request,
                Expense.objects.filter(date__gte=start, date__lte=end)
            )
            .values("date")
            .annotate(total=Sum("amount"))
            .order_by("date")
        )

        sales_map = {row["d"]: float(row["total"] or 0) for row in sales_qs}
        exp_map = {row["date"]: float(row["total"] or 0) for row in exp_qs}
        all_days = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

        rows = []
        total_sales = 0.0
        total_exp = 0.0

        for d in all_days:
            s = float(sales_map.get(d, 0))
            e = float(exp_map.get(d, 0))
            p = s - e
            total_sales += s
            total_exp += e
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "sales": round(s, 2),
                "expense": round(e, 2),
                "profit": round(p, 2),
            })

        return Response({
            "range": {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")},
            "summary": {
                "sales": round(total_sales, 2),
                "expense": round(total_exp, 2),
                "profit": round(total_sales - total_exp, 2),
            },
            "rows": rows
        })


@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsOwnerOrManagerOrPlatformAdmin])
def net_income_today(request):
    today = timezone.localdate()
    dec = DecimalField(max_digits=12, decimal_places=2)

    sales = (
        _shop_filter_or_all(
            request,
            Order.objects.filter(is_paid=True, created_at__date=today)
        )
        .aggregate(v=Coalesce(Sum(ORDER_TOTAL_FIELD), Value(0), output_field=dec))["v"]
    )

    expense = (
        _shop_filter_or_all(
            request,
            Expense.objects.filter(date=today)
        )
        .aggregate(v=Coalesce(Sum(EXPENSE_AMOUNT_FIELD), Value(0), output_field=dec))["v"]
    )

    net_income = sales - expense

    return Response({
        "date": str(today),
        "sales": float(sales),
        "expense": float(expense),
        "net_income": float(net_income),
    })


# =========================
# Legacy POS Web (session cart)
# =========================
@login_required
def pos_kasir_view(request):
    shop = _user_shop(request)
    if not shop and not request.user.is_superuser:
        raise Http404("Shop not found")

    products = Product.objects.filter(shop=shop).order_by("name")
    cart = request.session.get("cart", [])

    if request.method == "POST":
        product_id = str(request.POST.get("product_id") or "").strip()

        try:
            quantity = int(request.POST.get("quantity", 1))
        except Exception:
            quantity = 1

        if quantity < 1:
            quantity = 1

        found = False
        for item in cart:
            if str(item.get("product_id")) == product_id:
                item["quantity"] = int(item.get("quantity", 0) or 0) + quantity
                found = True
                break

        if not found and product_id:
            cart.append({"product_id": product_id, "quantity": quantity})

        request.session["cart"] = cart
        return redirect("pos_kasir")

    cart_items = []
    total = 0

    for item in cart:
        pid = item.get("product_id")
        qty = int(item.get("quantity", 0) or 0)
        if qty <= 0:
            continue

        try:
            product = Product.objects.get(id=int(pid), shop=shop)
        except Exception:
            continue

        subtotal = (product.sell_price or 0) * qty
        total += subtotal
        cart_items.append({
            "product": product,
            "quantity": qty,
            "subtotal": subtotal,
        })

    return render(request, "pos/pos_kasir.html", {
        "products": products,
        "cart_items": cart_items,
        "total": total,
    })


@login_required
def pos_remove_from_cart(request, product_id: int):
    cart = request.session.get("cart", [])
    cart = [item for item in cart if str(item.get("product_id")) != str(product_id)]
    request.session["cart"] = cart
    return redirect("pos_kasir")


@login_required
def pos_checkout(request):
    cart = request.session.get("cart", [])
    if not cart:
        return redirect("pos_kasir")

    if request.method != "POST":
        return redirect("pos_kasir")

    shop = _user_shop(request)
    if not shop:
        return redirect("pos_kasir")

    payment_method = (request.POST.get("payment_method") or "Cash").strip()

    try:
        with transaction.atomic():
            validated_items = []
            subtotal = Decimal("0.00")

            for item in cart:
                pid = item.get("product_id")
                qty = int(item.get("quantity", 0) or 0)
                if qty <= 0:
                    continue

                product = Product.objects.select_for_update().get(id=int(pid), shop=shop)

                if not product.sell_price or product.sell_price <= 0:
                    raise ValidationError(
                        f"Product '{product.name}' price is not set. Please update price."
                    )

                if product.track_stock and product.stock < qty:
                    raise ValidationError(
                        f"Stock not enough for '{product.name}'. Remaining {product.stock}, requested {qty}."
                    )

                validated_items.append((product, qty))
                subtotal += Decimal(product.sell_price) * qty

            if not validated_items:
                raise ValidationError("Cart is empty or invalid.")

            order = Order.objects.create(
                shop=shop,
                customer=None,
                payment_method=payment_method,
                subtotal=Decimal("0.00"),
                discount=Decimal("0.00"),
                tax=Decimal("0.00"),
                total=Decimal("0.00"),
                notes="",
                served_by=request.user,
                is_paid=True,
                default_order_type=(
                    Order.OrderType.TAKE_OUT
                    if shop.business_type == Shop.BusinessType.RESTAURANT
                    else Order.OrderType.GENERAL
                ),
                table_number="",
                delivery_address="",
                delivery_fee=Decimal("0.00"),
            )

            for product, qty in validated_items:
                before = product.stock
                after = before - qty

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=qty,
                    price=product.sell_price,
                    weight_unit=product.unit,
                    order_type=(
                    OrderItem.OrderType.TAKE_OUT
                        if shop.business_type == Shop.BusinessType.RESTAURANT
                        else OrderItem.OrderType.GENERAL
                    ),
                )

                product.stock = after
                product.save(update_fields=["stock"])

                StockMovement.objects.create(
                    shop=shop,
                    product=product,
                    movement_type=StockMovement.Type.SALE,
                    quantity_delta=-qty,
                    before_stock=before,
                    after_stock=after,
                    note=f"Order #{order.id}",
                    ref_model="Order",
                    ref_id=order.id,
                    created_by=request.user,
                )

            tax = Decimal("0.00")
            discount = Decimal("0.00")
            total = subtotal + tax - discount

            order.subtotal = subtotal
            order.tax = tax
            order.discount = discount
            order.total = total
            order.save(update_fields=["subtotal", "tax", "discount", "total"])

    except ValidationError as e:
        error_text = str(e.detail[0] if hasattr(e, "detail") and isinstance(e.detail, list) else e.detail if hasattr(e, "detail") else str(e))
        return render(request, "pos/pos_kasir.html", {
            "products": Product.objects.filter(shop=shop).order_by("name"),
            "cart_items": [],
            "total": 0,
            "error": error_text,
        })
    except Product.DoesNotExist:
        return render(request, "pos/pos_kasir.html", {
            "products": Product.objects.filter(shop=shop).order_by("name"),
            "cart_items": [],
            "total": 0,
            "error": "One or more products are no longer available.",
        })

    request.session["cart"] = []
    return redirect("pos_kasir")


# =========================
# Admin Report Views
# =========================
@role_required(["owner", "manager"])
def expense_report_view(request):
    expenses = _shop_filter_or_all(
        request,
        Expense.objects.all().order_by("-date", "-time", "-id")
    )
    context = _admin_context(request, "Expense Report")
    context.update({"expenses": expenses})
    return render(request, "pos/expense_report.html", context)


@role_required(["owner", "manager"])
def expense_chart_view(request):
    data = (
        _shop_filter_or_all(request, Expense.objects.all())
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )

    labels_list = [d["month"].strftime("%B %Y") for d in data if d.get("month")]
    totals_list = [float(d.get("total") or 0) for d in data if d.get("month")]

    context = _admin_context(request, "Expense Chart")
    context.update({
        "labels": json.dumps(labels_list),
        "totals": json.dumps(totals_list),
    })

    return _render_with_fallback(
        request,
        ["pos/expense_chart.html", "pos/expense_cart.html"],
        context
    )


@role_required(["owner", "manager"])
def sales_report_view(request):
    month = request.GET.get("month")
    rows = []

    items = _shop_filter_or_all(
        request,
        OrderItem.objects.select_related("order", "product", "weight_unit").filter(order__is_paid=True),
        shop_field="order__shop"
    )

    if month:
        try:
            year, month_number = month.split("-")
            items = items.filter(order__created_at__year=year, order__created_at__month=month_number)
        except ValueError:
            pass

    for item in items:
        rows.append({
            "product_name": item.product.name,
            "invoice_id": item.order.invoice_number or f"INV{item.order.id:015d}",
            "qty": item.quantity,
            "weight": f"{item.product.weight} {item.weight_unit.name}" if item.weight_unit else "-",
            "total_price": item.quantity * item.price,
            "order_date": item.order.created_at.strftime("%d %B, %Y"),
        })

    context = _admin_context(request, "Sales Report")
    context.update({"rows": rows})
    return render(request, "pos/sales_report.html", context)


@role_required(["owner", "manager"])
def sales_chart_view(request):
    line_total = ExpressionWrapper(
        F("price") * F("quantity"),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    data = (
        _shop_filter_or_all(
            request,
            OrderItem.objects.filter(order__is_paid=True),
            shop_field="order__shop"
        )
        .annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(total_sales=Sum(line_total))
        .order_by("month")
    )

    labels_list = [d["month"].strftime("%B %Y") for d in data if d.get("month")]
    sales_list = [float(d.get("total_sales") or 0) for d in data if d.get("month")]

    total_order_price = float(sum(sales_list))
    total_tax = 0.0
    total_discount = 0.0
    net_sales = total_order_price - total_discount + total_tax

    context = _admin_context(request, "Sales Chart")
    context.update({
        "labels": json.dumps(labels_list),
        "sales": json.dumps(sales_list),
        "total_order_price": total_order_price,
        "total_tax": total_tax,
        "total_discount": total_discount,
        "net_sales": net_sales,
    })

    return _render_with_fallback(
        request,
        ["pos/sales_chart.html", "pos/sales_cart.html"],
        context
    )


@role_required(["owner", "manager"])
def daily_profit_dashboard_view(request):
    start = parse_date(request.GET.get("start") or "")
    end = parse_date(request.GET.get("end") or "")

    today = timezone.localdate()
    if not end:
        end = today
    if not start:
        start = end - timedelta(days=13)

    sales_qs = (
        _shop_filter_or_all(
            request,
            Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
        )
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(total=Sum("total"))
        .order_by("d")
    )

    exp_qs = (
        _shop_filter_or_all(
            request,
            Expense.objects.filter(date__gte=start, date__lte=end)
        )
        .values("date")
        .annotate(total=Sum("amount"))
        .order_by("date")
    )

    sales_map = {row["d"]: float(row["total"] or 0) for row in sales_qs}
    exp_map = {row["date"]: float(row["total"] or 0) for row in exp_qs}
    all_days = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

    labels, sales, expense, profit = [], [], [], []
    total_sales = 0.0
    total_exp = 0.0

    for d in all_days:
        s = float(sales_map.get(d, 0))
        e = float(exp_map.get(d, 0))
        p = s - e
        labels.append(d.strftime("%d %b"))
        sales.append(round(s, 2))
        expense.append(round(e, 2))
        profit.append(round(p, 2))
        total_sales += s
        total_exp += e

    ctx = _admin_context(request, "Daily Profit Dashboard")
    ctx.update({
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": end.strftime("%Y-%m-%d"),
        "total_sales": round(total_sales, 2),
        "total_expense": round(total_exp, 2),
        "net_profit": round(total_sales - total_exp, 2),
        "labels": json.dumps(labels),
        "sales": json.dumps(sales),
        "expense": json.dumps(expense),
        "profit": json.dumps(profit),
    })

    return render(request, "pos/daily_profit_dashboard.html", ctx)


@role_required(["owner", "manager"])
def monthly_pl_dashboard_view(request):
    data_sales = (
        _shop_filter_or_all(
            request,
            Order.objects.filter(is_paid=True)
        )
        .annotate(m=TruncMonth("created_at"))
        .values("m")
        .annotate(total=Sum("total"))
        .order_by("m")
    )

    data_exp = (
        _shop_filter_or_all(
            request,
            Expense.objects.all()
        )
        .annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(total=Sum("amount"))
        .order_by("m")
    )

    sales_map = {r["m"]: float(r["total"] or 0) for r in data_sales}
    exp_map = {r["m"]: float(r["total"] or 0) for r in data_exp}
    all_months = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

    labels, sales, expense, profit = [], [], [], []
    for m in all_months:
        s = float(sales_map.get(m, 0))
        e = float(exp_map.get(m, 0))
        labels.append(m.strftime("%b %Y"))
        sales.append(round(s, 2))
        expense.append(round(e, 2))
        profit.append(round(s - e, 2))

    ctx = _admin_context(request, "Monthly Profit & Loss")
    ctx.update({
        "labels": json.dumps(labels),
        "sales": json.dumps(sales),
        "expense": json.dumps(expense),
        "profit": json.dumps(profit),
        "total_sales": round(sum(sales), 2),
        "total_expense": round(sum(expense), 2),
        "net_profit": round(sum(profit), 2),
    })
    return render(request, "pos/monthly_pl_dashboard.html", ctx)


# =========================
# API ViewSets
# =========================
class CustomerViewSet(TenantModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    tenant_model = Customer
    tenant_ordering = ("-id",)


class SupplierViewSet(TenantModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
    tenant_model = Supplier
    tenant_ordering = ("-id",)


class CategoryViewSet(TenantModelViewSet):
    serializer_class = CategorySerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]
    tenant_model = Category
    tenant_ordering = ("name",)


class ProductViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = _tenant_queryset(self.request, Product).select_related(
            "category", "supplier", "unit"
        ).order_by("-id")

        category = self.request.query_params.get("category")
        if category and str(category).lower() not in ("all", "-1"):
            try:
                qs = qs.filter(category_id=int(category))
            except (ValueError, TypeError):
                pass

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                models.Q(name__icontains=search) |
                models.Q(code__icontains=search) |
                models.Q(sku__icontains=search)
            )

        track_stock = self.request.query_params.get("track_stock")
        if track_stock is not None:
            value = str(track_stock).strip().lower()
            if value in ("true", "1", "yes"):
                qs = qs.filter(track_stock=True)
            elif value in ("false", "0", "no"):
                qs = qs.filter(track_stock=False)

        return qs

    def perform_create(self, serializer):
        if self.request.user.is_superuser:
            raise ValidationError("Platform admin cannot create tenant product from this endpoint.")

        shop = _require_user_shop(self.request)
        serializer.save(shop=shop)

class OrderViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return Order.objects.none()

        qs = Order.objects.filter(shop=shop).prefetch_related(
            "items",
            "items__product",
            "payments",
            "payments__payment_method",
            "payments__bank_account",
        ).select_related(
            "customer",
            "served_by",
        ).order_by("-created_at")

        customer_id = self.request.query_params.get("customer")
        payment_method = self.request.query_params.get("payment_method")
        is_paid = self.request.query_params.get("is_paid")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if customer_id:
            try:
                qs = qs.filter(customer_id=int(customer_id))
            except (TypeError, ValueError):
                pass

        if payment_method:
            qs = qs.filter(payment_method__iexact=payment_method)

        if is_paid is not None:
            val = str(is_paid).lower().strip()
            if val in ("true", "1", "yes"):
                qs = qs.filter(is_paid=True)
            elif val in ("false", "0", "no"):
                qs = qs.filter(is_paid=False)

        if date_from:
            parsed = parse_date(date_from)
            if parsed:
                qs = qs.filter(created_at__date__gte=parsed)

        if date_to:
            parsed = parse_date(date_to)
            if parsed:
                qs = qs.filter(created_at__date__lte=parsed)

        return qs

    def perform_create(self, serializer):
        shop = _require_user_shop(self.request)
        serializer.save(
            served_by=self.request.user,
            shop=shop
        )


class PurchaseViewSet(RequestContextMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return Purchase.objects.none()

        return Purchase.objects.filter(shop=shop).select_related(
            "supplier", "created_by"
        ).prefetch_related(
            "items", "items__product"
        ).order_by("-id")

    def get_serializer_class(self):
        if self.action == "create":
            return PurchaseCreateSerializer
        return PurchaseSerializer

    def create(self, request, *args, **kwargs):
        shop = _require_user_shop(request)

        ser = PurchaseCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        purchase = ser.save(shop=shop, created_by=request.user)
        out = PurchaseSerializer(purchase, context={"request": request}).data
        return Response(out, status=status.HTTP_201_CREATED)


class ExpenseViewSet(TenantModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]
    tenant_model = Expense
    tenant_ordering = ("-date", "-time", "-id")


class BannerViewSet(ModelViewSet):
    serializer_class = BannerSerializer
    permission_classes = [OwnerOnlyWriteOrRead]

    def get_queryset(self):
        qs = Banner.objects.all().order_by("-id")

        if _model_has_field(Banner, "shop"):
            return _tenant_queryset(self.request, Banner).order_by("-id")

        return qs

    def perform_create(self, serializer):
        if _model_has_field(Banner, "shop"):
            if self.request.user.is_superuser:
                raise ValidationError("Platform admin cannot create tenant banner from this endpoint.")

            shop = _require_user_shop(self.request)
            serializer.save(shop=shop)
            return

        serializer.save()


class UnitViewSet(TenantModelViewSet):
    serializer_class = UnitSerializer
    permission_classes = [OwnerOrManagerWriteOrRead]
    tenant_model = Unit
    tenant_ordering = ("name",)


class PaymentMethodViewSet(TenantReadOnlyModelViewSet):
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsAuthenticated]
    tenant_model = PaymentMethod
    tenant_ordering = ("name",)

    def get_queryset(self):
        return _tenant_queryset(
            self.request,
            PaymentMethod,
            is_active=True
        ).order_by("name")


class BankAccountViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = BankAccountSerializer
    permission_classes = [IsAuthenticated, BankAccountPermission]

    def get_queryset(self):
        user = self.request.user

        if user.is_superuser:
            return BankAccount.objects.select_related("shop").all().order_by("bank_name", "name")

        shop = _user_shop(self.request)
        if not shop:
            return BankAccount.objects.none()

        qs = BankAccount.objects.select_related("shop").filter(
            shop=shop
        ).order_by("bank_name", "name")

        is_active = self.request.query_params.get("is_active")
        account_type = self.request.query_params.get("account_type")
        search = (self.request.query_params.get("search") or "").strip()

        if is_active is not None:
            val = str(is_active).lower().strip()
            if val in ("true", "1", "yes"):
                qs = qs.filter(is_active=True)
            elif val in ("false", "0", "no"):
                qs = qs.filter(is_active=False)

        if account_type:
            qs = qs.filter(account_type=account_type)

        if search:
            qs = qs.filter(
                models.Q(name__icontains=search) |
                models.Q(bank_name__icontains=search) |
                models.Q(account_number__icontains=search) |
                models.Q(account_holder__icontains=search)
            )

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        shop = _user_shop(self.request)

        if user.is_superuser:
            raise ValidationError("Platform admin cannot create tenant bank account from this endpoint.")

        if not shop:
            raise ValidationError("User tidak memiliki shop.")

        serializer.save(shop=shop)

    def perform_update(self, serializer):
        user = self.request.user
        shop = _user_shop(self.request)
        instance = self.get_object()

        if user.is_superuser:
            raise ValidationError("Platform admin cannot update tenant bank account from this endpoint.")

        if not shop:
            raise ValidationError("User tidak memiliki shop.")

        if instance.shop_id != shop.id:
            raise ValidationError("Bank account ini tidak berasal dari shop Anda.")

        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        shop = _user_shop(self.request)

        if user.is_superuser:
            raise ValidationError("Platform admin cannot delete tenant bank account from this endpoint.")

        if not shop:
            raise ValidationError("User tidak memiliki shop.")

        if instance.shop_id != shop.id:
            raise ValidationError("Bank account ini tidak berasal dari shop Anda.")

        if instance.sale_payments.exists():
            raise ValidationError("Bank account tidak bisa dihapus karena sudah dipakai pada pembayaran.")

        if instance.ledgers.exists():
            raise ValidationError("Bank account tidak bisa dihapus karena sudah memiliki ledger.")

        instance.delete()


class InventoryCountViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = InventoryCountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return InventoryCount.objects.none()

        return InventoryCount.objects.filter(
            shop=shop
        ).order_by("-counted_at", "-id")

    def perform_create(self, serializer):
        shop = _require_user_shop(self.request)
        serializer.save(
            counted_by=self.request.user,
            shop=shop
        )

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        shop = _require_user_shop(request)

        with transaction.atomic():
            inventory = InventoryCount.objects.select_for_update().get(pk=pk, shop=shop)

            if inventory.status == InventoryCount.STATUS_COMPLETED:
                return Response({"error": "Inventory already finalized"}, status=400)

            items = inventory.items.select_related("product")

            for item in items:
                product = Product.objects.select_for_update().get(pk=item.product_id, shop=shop)
                if not product.track_stock:
                    continue
                
                difference = item.counted_stock - item.system_stock

                if difference != 0:
                    product.stock = item.counted_stock
                    product.save(update_fields=["stock"])

                    StockMovement.objects.create(
                        shop=shop,
                        product=product,
                        movement_type=StockMovement.Type.COUNT,
                        quantity_delta=difference,
                        before_stock=item.system_stock,
                        after_stock=item.counted_stock,
                        note=f"Inventory Count #{inventory.id}",
                        created_by=request.user,
                    )

            inventory.status = InventoryCount.STATUS_COMPLETED
            inventory.save(update_fields=["status"])

        return Response({"status": "Finalized successfully"})


class SalePaymentViewSet(RequestContextMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SalePaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return SalePayment.objects.none()

        qs = SalePayment.objects.select_related(
            "order",
            "payment_method",
            "bank_account",
            "created_by",
        ).filter(
            order__shop=shop
        ).order_by("-paid_at", "-id")

        order_id = self.request.query_params.get("order")
        payment_method_id = self.request.query_params.get("payment_method")
        bank_account_id = self.request.query_params.get("bank_account")

        if order_id:
            try:
                qs = qs.filter(order_id=int(order_id))
            except (TypeError, ValueError):
                pass

        if payment_method_id:
            try:
                qs = qs.filter(payment_method_id=int(payment_method_id))
            except (TypeError, ValueError):
                pass

        if bank_account_id:
            try:
                qs = qs.filter(bank_account_id=int(bank_account_id))
            except (TypeError, ValueError):
                pass

        return qs


class BankLedgerViewSet(RequestContextMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = BankLedgerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return BankLedger.objects.none()

        qs = BankLedger.objects.select_related(
            "bank_account",
            "reference_order",
            "reference_payment",
            "created_by",
        ).filter(
            bank_account__shop=shop
        ).order_by("-created_at", "-id")

        bank_account_id = self.request.query_params.get("bank_account")
        transaction_type = self.request.query_params.get("transaction_type")
        direction = self.request.query_params.get("direction")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        if bank_account_id:
            try:
                qs = qs.filter(bank_account_id=int(bank_account_id))
            except (TypeError, ValueError):
                pass

        if transaction_type:
            qs = qs.filter(transaction_type=transaction_type)

        if direction:
            qs = qs.filter(direction=direction)

        if date_from:
            parsed = parse_date(date_from)
            if parsed:
                qs = qs.filter(created_at__date__gte=parsed)

        if date_to:
            parsed = parse_date(date_to)
            if parsed:
                qs = qs.filter(created_at__date__lte=parsed)

        return qs


class ProductReturnViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = ProductReturnSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return ProductReturn.objects.none()

        return ProductReturn.objects.filter(
            shop=shop
        ).prefetch_related("items").order_by("-returned_at", "-id")

    def perform_create(self, serializer):
        shop = _require_user_shop(self.request)
        serializer.save(
            returned_by=self.request.user,
            shop=shop
        )


class StockMovementViewSet(RequestContextMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return StockMovement.objects.none()

        qs = StockMovement.objects.select_related(
            "product", "created_by"
        ).filter(
            shop=shop
        ).order_by("-created_at", "-id")

        product_id = self.request.query_params.get("product")
        mtype = self.request.query_params.get("type")

        if product_id:
            try:
                qs = qs.filter(product_id=int(product_id))
            except (TypeError, ValueError):
                pass

        if mtype:
            qs = qs.filter(movement_type=mtype)

        return qs


class StockAdjustmentViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = StockAdjustmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        shop = _user_shop(self.request)
        if not shop:
            return StockAdjustment.objects.none()

        return StockAdjustment.objects.filter(
            shop=shop
        ).order_by("-adjusted_at", "-id")

    @transaction.atomic
    def perform_create(self, serializer):
        shop = _require_user_shop(self.request)
        serializer.save(
            adjusted_by=self.request.user,
            shop=shop
        )


# =========================
# Receipt PDF
# =========================
def _link_callback(uri, rel):
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
        if os.path.isfile(path):
            return path

    if uri.startswith(settings.STATIC_URL):
        path = os.path.join(settings.STATIC_ROOT, uri.replace(settings.STATIC_URL, ""))
        if os.path.isfile(path):
            return path

    return uri


@login_required
def order_receipt_pdf(request, order_id):
    qs = Order.objects.prefetch_related(
        "items__product", "items__weight_unit"
    ).select_related(
        "served_by", "shop"
    )

    if request.user.is_superuser:
        order = get_object_or_404(qs, id=order_id)
    else:
        order = get_object_or_404(qs, id=order_id, shop=_user_shop(request))

    shop = order.shop

    TYPE_META = {
        "DINE_IN": {"label": "DINE IN", "icon": "■■"},
        "TAKE_OUT": {"label": "TAKE OUT", "icon": "■"},
        "DELIVERY": {"label": "DELIVERY", "icon": "▲"},
        "GENERAL": {"label": "GENERAL", "icon": "•"},
    }

    receipt_items = []
    for item in order.items.all():
        unit_price = item.price or 0
        qty = item.quantity or 0
        line_total = qty * unit_price
        meta = TYPE_META.get(item.order_type, {"label": (item.order_type or "-"), "icon": "•"})

        receipt_items.append({
            "name": item.product.name if item.product else "-",
            "qty": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "order_type": meta["label"],
            "order_type_icon": meta["icon"],
        })

    template = get_template("pos/order_receipt.html")
    html = template.render({
        "order": order,
        "shop": shop,
        "receipt_items": receipt_items,
    })

    result = io.BytesIO()
    pdf = pisa.pisaDocument(
        io.BytesIO(html.encode("UTF-8")),
        result,
        link_callback=_link_callback
    )

    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type="application/pdf")
    return HttpResponse("Error generating PDF", status=500)


# =========================
# Print barcodes (API) - PDF
# =========================
@api_view(["GET"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_print_barcodes(request):
    ids = (request.GET.get("ids") or "").strip()
    if not ids:
        return Response({"detail": "ids is required. Example: ?ids=1,2,3"}, status=400)

    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except Exception:
        return Response({"detail": "Invalid ids format"}, status=400)

    products = Product.objects.filter(id__in=id_list).order_by("name")
    if not request.user.is_superuser:
        shop = _user_shop(request)
        if not shop:
            return Response({"detail": "User tidak memiliki shop."}, status=400)
        products = products.filter(shop=shop)

    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="product_barcodes.pdf"'
    c = canvas.Canvas(resp, pagesize=A4)
    width, height = A4

    label_w = 70 * mm
    label_h = 35 * mm
    margin_x = 10 * mm
    margin_y = 10 * mm
    gap_x = 5 * mm
    gap_y = 5 * mm
    cols = int((width - 2 * margin_x + gap_x) // (label_w + gap_x)) or 1

    x = margin_x
    y = height - margin_y - label_h

    def draw_label(prod, x0, y0):
        c.roundRect(x0, y0, label_w, label_h, 6, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0 + 4 * mm, y0 + label_h - 7 * mm, (prod.name or "")[:26])

        c.setFont("Helvetica", 8)
        if getattr(prod, "sku", ""):
            c.drawString(x0 + 4 * mm, y0 + label_h - 12 * mm, f"SKU: {(prod.sku or '')[:22]}")
        c.drawString(x0 + 4 * mm, y0 + label_h - 17 * mm, f"Price: ${prod.sell_price}")

        value = (prod.code or "").strip()
        if value:
            bc = code128.Code128(value, barHeight=12 * mm, humanReadable=True)
            bc.drawOn(c, x0 + 4 * mm, y0 + 4 * mm)

    prods = list(products)
    for i, p in enumerate(prods):
        if y < margin_y:
            c.showPage()
            y = height - margin_y - label_h
            x = margin_x

        draw_label(p, x, y)

        if (i + 1) % cols == 0:
            x = margin_x
            y -= (label_h + gap_y)
        else:
            x += (label_w + gap_x)

    c.showPage()
    c.save()
    return resp


@staff_member_required
def admin_print_barcodes(request):
    ids = (request.GET.get("ids") or "").strip()
    if not ids:
        return HttpResponse("Missing ids. Example: ?ids=1,2,3", status=400)

    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except Exception:
        return HttpResponse("Invalid ids format. Example: ?ids=1,2,3", status=400)

    products = Product.objects.filter(id__in=id_list).order_by("name")
    if not request.user.is_superuser:
        shop = _user_shop(request)
        if not shop:
            return HttpResponse("User tidak memiliki shop.", status=400)
        products = products.filter(shop=shop)

    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="product_barcodes.pdf"'
    c = canvas.Canvas(resp, pagesize=A4)
    width, height = A4

    label_w = 70 * mm
    label_h = 35 * mm
    margin_x = 10 * mm
    margin_y = 10 * mm
    gap_x = 5 * mm
    gap_y = 5 * mm
    cols = int((width - 2 * margin_x + gap_x) // (label_w + gap_x)) or 1

    x = margin_x
    y = height - margin_y - label_h

    def draw_label(prod, x0, y0):
        c.roundRect(x0, y0, label_w, label_h, 6, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0 + 4 * mm, y0 + label_h - 7 * mm, (prod.name or "")[:26])

        c.setFont("Helvetica", 8)
        if getattr(prod, "sku", ""):
            c.drawString(x0 + 4 * mm, y0 + label_h - 12 * mm, f"SKU: {(prod.sku or '')[:22]}")
        c.drawString(x0 + 4 * mm, y0 + label_h - 17 * mm, f"Price: ${getattr(prod, 'sell_price', '')}")

        value = (getattr(prod, "code", "") or "").strip()
        if value:
            bc = code128.Code128(value, barHeight=12 * mm, humanReadable=True)
            bc.drawOn(c, x0 + 4 * mm, y0 + 4 * mm)
        else:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(x0 + 4 * mm, y0 + 6 * mm, "No barcode (code)")

    prods = list(products)
    for i, p in enumerate(prods):
        if y < margin_y:
            c.showPage()
            y = height - margin_y - label_h
            x = margin_x

        draw_label(p, x, y)

        if (i + 1) % cols == 0:
            x = margin_x
            y -= (label_h + gap_y)
        else:
            x += (label_w + gap_x)

    c.showPage()
    c.save()
    return resp


# =========================
# Auth API
# =========================
def build_permissions_for_user(user):
    perms = set(user.get_feature_permissions())

    role = (getattr(user, "role", "") or "").lower().strip()

    if user.is_superuser:
        perms.update([
            "reports.view",
            "settings.manage",
            "owner_chat.use",
            "platform.manage_shops",
            "platform.manage_users",
        ])

    if role == "owner":
        perms.update([
            "reports.view",
            "settings.manage",
            "owner_chat.use",
            "shop.manage_users",
            "shop.manage_settings",
        ])

    return sorted(perms)


@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    shop_code = (request.data.get("shop_code") or "").strip().upper()
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    if not username or not password:
        return Response(
            {"detail": "username and password are required"},
            status=400
        )

    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"detail": "Invalid credentials"}, status=401)

    if not user.is_active:
        return Response({"detail": "User is inactive"}, status=403)

    role = (user.role or "").lower().strip()

    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    permissions = build_permissions_for_user(user)

    if user.is_superuser:
        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "username": user.get_username(),
                "full_name": user.get_full_name().strip() or user.username,
                "email": user.email or "",
                "role": role,
                "role_label": user.role_label,
                "shop_id": None,
                "shop_name": "",
                "shop_code": "",
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
                "is_platform_admin": True,
                "is_shop_user": False,
                "is_shop_owner": False,
                "is_shop_manager": False,
                "is_shop_cashier": False,
            },
            "shop": None,
            "permissions": permissions
        }, status=200)

    if not shop_code:
        return Response(
            {"detail": "shop_code is required"},
            status=400
        )

    try:
        shop = Shop.objects.get(code=shop_code, is_active=True)
    except Shop.DoesNotExist:
        return Response({"detail": "Invalid shop code"}, status=401)

    if not user.shop_id:
        return Response({"detail": "User is not assigned to any shop"}, status=403)

    if user.shop_id != shop.id:
        return Response({"detail": "This user does not belong to the selected shop"}, status=403)

    shop_data = ShopSerializer(user.shop, context={"request": request}).data if user.shop else None

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.get_username(),
            "full_name": user.get_full_name().strip() or user.username,
            "email": user.email or "",
            "role": role,
            "role_label": user.role_label,
            "shop_id": user.shop_id,
            "shop_name": user.shop.name if user.shop else "",
            "shop_code": user.shop.code if user.shop else "",
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "is_platform_admin": False,
            "is_shop_user": bool(user.shop_id),
            "is_shop_owner": bool(user.shop_id and role == "owner"),
            "is_shop_manager": bool(user.shop_id and role == "manager"),
            "is_shop_cashier": bool(user.shop_id and role == "cashier"),
        },
        "shop": shop_data,
        "permissions": permissions
    }, status=200)


class MyShopAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        if request.user.is_superuser:
            return Response(
                {"detail": "Platform admin has no tenant shop context."},
                status=400
            )

        if not request.user.shop:
            return Response({"detail": "No shop assigned."}, status=404)

        data = ShopSerializer(request.user.shop, context={"request": request}).data
        return Response(data)

    def patch(self, request):
        if request.user.is_superuser:
            return Response(
                {"detail": "Platform admin has no tenant shop context."},
                status=400
            )

        user = request.user
        role = (user.role or "").lower().strip()

        if role != "owner":
            return Response(
                {"detail": "Only shop owner can update shop settings."},
                status=403
            )

        if not user.shop:
            return Response({"detail": "No shop assigned."}, status=404)

        ser = ShopSerializer(
            user.shop,
            data=request.data,
            partial=True,
            context={"request": request}
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


# =========================
# Shop API
# =========================
class ShopViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = ShopSerializer
    permission_classes = [IsPlatformAdminOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        if self.request.user.is_superuser:
            return Shop.objects.all().order_by("-id")
        return Shop.objects.none()

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()
        
        
# =========================
# Staff API
# =========================
class StaffViewSet(RequestContextMixin, viewsets.ModelViewSet):
    serializer_class = StaffSerializer
    permission_classes = [IsAuthenticated, ShopStaffPermission]

    def get_queryset(self):
        user = self.request.user

        if user.is_superuser:
            return CustomUser.objects.select_related("shop").all().order_by("-id")

        shop = _user_shop(self.request)
        if not shop:
            return CustomUser.objects.none()

        qs = CustomUser.objects.select_related("shop").filter(shop=shop).order_by("-id")

        search = (self.request.query_params.get("search") or "").strip()
        role = (self.request.query_params.get("role") or "").strip().lower()
        is_active = self.request.query_params.get("is_active")

        if search:
            qs = qs.filter(
                models.Q(username__icontains=search) |
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search) |
                models.Q(email__icontains=search)
            )

        if role:
            qs = qs.filter(role=role)

        if is_active is not None:
            val = str(is_active).lower().strip()
            if val in ("true", "1", "yes"):
                qs = qs.filter(is_active=True)
            elif val in ("false", "0", "no"):
                qs = qs.filter(is_active=False)

        return qs

    def perform_create(self, serializer):
        shop = _require_user_shop(self.request)
        serializer.save(shop=shop)

    def perform_update(self, serializer):
        instance = self.get_object()
        shop = _require_user_shop(self.request)

        if instance.shop_id != shop.id:
            raise ValidationError("Staff ini tidak berasal dari shop Anda.")

        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        shop = _require_user_shop(self.request)

        if instance.shop_id != shop.id:
            raise ValidationError("Staff ini tidak berasal dari shop Anda.")

        if instance.id == user.id:
            raise ValidationError("Anda tidak bisa menghapus akun Anda sendiri.")

        instance.delete()