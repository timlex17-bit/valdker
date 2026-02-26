import io
import os
import json
from datetime import date, timedelta

from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from pos.permissions import IsSuperAdminOnly, AdminOnlyWriteOrRead
from django.http import HttpResponse
from django.contrib.auth import authenticate
from django.db import models
from django.db.models import Sum, Value, DecimalField, F, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.shortcuts import render, redirect, get_object_or_404
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication
from pos.models import StockAdjustment

from rest_framework import viewsets
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from rest_framework.permissions import IsAuthenticated
from decimal import Decimal

from xhtml2pdf import pisa
from django.db import transaction
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128

from .decorators import role_required
from .models import (
    Order, OrderItem, Customer, Supplier, Product, Category, Unit, Banner, Shop, Expense,
    StockAdjustment, InventoryCount, ProductReturn, StockMovement
)
from .serializers import (
    OrderSerializer, CustomerSerializer, SupplierSerializer,
    ProductSerializer, CategorySerializer, UnitSerializer, ShopSerializer,
    ExpenseSerializer, BannerSerializer,
    StockAdjustmentSerializer, InventoryCountSerializer, ProductReturnSerializer, StockMovementSerializer
)

class DailyProfitReportAPIView(APIView):
    permission_classes = [IsSuperAdminOnly]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        today = timezone.localdate()
        if not end:
            end = today
        if not start:
            start = end - timedelta(days=13)

        sales_qs = (
            Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(total=Coalesce(Sum("total"), Value(0), output_field=DecimalField(max_digits=18, decimal_places=2)))
            .order_by("d")
        )

        exp_qs = (
            Expense.objects.filter(date__gte=start, date__lte=end)
            .values("date")
            .annotate(total=Coalesce(Sum("amount"), Value(0), output_field=DecimalField(max_digits=18, decimal_places=2)))
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

# =========================
# Helpers for Admin/Jazzmin
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


# =========================
# Legacy POS Web (session cart) - keep urls.py safe
# =========================
@login_required
def pos_kasir_view(request):
    """
    Legacy POS web (session cart).
    Kept for compatibility with existing urls.py.
    DOES NOT affect Android/Vue APIs.
    """
    products = Product.objects.all().order_by("name")
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
            product = Product.objects.get(id=int(pid))
        except Exception:
            continue

        subtotal = (product.sell_price or 0) * qty
        total += subtotal
        cart_items.append({
            "product": product,
            "quantity": qty,
            "subtotal": subtotal
        })

    return render(request, "pos/pos_kasir.html", {
        "products": products,
        "cart_items": cart_items,
        "total": total
    })


@login_required
def pos_remove_from_cart(request, product_id: int):
    cart = request.session.get("cart", [])
    cart = [item for item in cart if str(item.get("product_id")) != str(product_id)]
    request.session["cart"] = cart
    return redirect("pos_kasir")


@login_required
def pos_checkout(request):
    """
    Checkout legacy session cart -> create Order + OrderItems.
    """
    cart = request.session.get("cart", [])
    if not cart:
        return redirect("pos_kasir")

    if request.method != "POST":
        return redirect("pos_kasir")

    payment_method = (request.POST.get("payment_method") or "Cash").strip()

    order = Order.objects.create(
        customer=None,
        payment_method=payment_method,
        subtotal=0,
        discount=0,
        tax=0,
        total=0,
        notes="",
        served_by=request.user,
        is_paid=True,

        default_order_type=Order.OrderType.TAKE_OUT,
        table_number="",
        delivery_address="",
        delivery_fee=0,
    )

    subtotal = 0

    for item in cart:
        pid = item.get("product_id")
        qty = int(item.get("quantity", 0) or 0)
        if qty <= 0:
            continue

        product = get_object_or_404(Product, id=int(pid))

        if not product.sell_price or product.sell_price <= 0:
            return render(request, "pos/pos_kasir.html", {
                "products": Product.objects.all().order_by("name"),
                "cart_items": [],
                "total": 0,
                "error": f"Product '{product.name}' price is not set. Please update price."
            })

        product.refresh_from_db()
        if product.stock < qty:
            return render(request, "pos/pos_kasir.html", {
                "products": Product.objects.all().order_by("name"),
                "cart_items": [],
                "total": 0,
                "error": f"Stock not enough for '{product.name}'. Remaining {product.stock}, requested {qty}."
            })

        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=qty,
            price=product.sell_price,
            weight_unit=product.unit,
            order_type=OrderItem.OrderType.TAKE_OUT,
        )

        Product.objects.filter(id=product.id).update(stock=F("stock") - qty)
        subtotal += (product.sell_price * qty)

    tax = 0
    discount = 0
    total = subtotal + tax - discount

    order.subtotal = subtotal
    order.tax = tax
    order.discount = discount
    order.total = total
    order.save()

    request.session["cart"] = []
    return redirect("pos_kasir")


# =========================
# Admin Report Views (keep old urls safe)
# =========================
@role_required(["admin", "manager", "cashier"])
def expense_report_view(request):
    expenses = Expense.objects.all().order_by("-date", "-time", "-id")
    context = _admin_context(request, "Expense Report")
    context.update({"expenses": expenses})
    return render(request, "pos/expense_report.html", context)


@role_required(["admin", "manager", "cashier"])
def expense_chart_view(request):
    data = (
        Expense.objects
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


@role_required(["admin", "manager", "cashier"])
def sales_report_view(request):
    month = request.GET.get("month")
    rows = []

    items = OrderItem.objects.select_related("order", "product", "weight_unit")
    if month:
        year, month_number = month.split("-")
        items = items.filter(order__created_at__year=year, order__created_at__month=month_number)

    for item in items:
        rows.append({
            "product_name": item.product.name,
            "invoice_id": f"INV{item.order.id:015d}",
            "qty": item.quantity,
            "weight": f"{item.product.weight} {item.weight_unit.name}" if item.weight_unit else "-",
            "total_price": item.quantity * item.price,
            "order_date": item.order.created_at.strftime("%d %B, %Y"),
        })

    context = _admin_context(request, "Sales Report")
    context.update({"rows": rows})
    return render(request, "pos/sales_report.html", context)


@role_required(["admin", "manager", "cashier"])
def sales_chart_view(request):
    line_total = ExpressionWrapper(
        F("price") * F("quantity"),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    data = (
        OrderItem.objects
        .filter(order__is_paid=True)
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


@role_required(["admin", "manager", "cashier"])
def daily_profit_dashboard_view(request):
    start = parse_date(request.GET.get("start") or "")
    end = parse_date(request.GET.get("end") or "")

    today = timezone.localdate()
    if not end:
        end = today
    if not start:
        start = end - timedelta(days=13)

    sales_qs = (
        Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(total=Sum("total"))
        .order_by("d")
    )

    exp_qs = (
        Expense.objects.filter(date__gte=start, date__lte=end)
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


@role_required(["admin", "manager", "cashier"])
def monthly_pl_dashboard_view(request):
    data_sales = (
        Order.objects.filter(is_paid=True)
        .annotate(m=TruncMonth("created_at"))
        .values("m")
        .annotate(total=Sum("total"))
        .order_by("m")
    )
    data_exp = (
        Expense.objects
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


ORDER_TOTAL_FIELD = "total"
EXPENSE_AMOUNT_FIELD = "amount"


# =========================
# Profit APIs (needed by pos/urls.py import)
# =========================
class MonthlyPLReportAPIView(APIView):
    permission_classes = [IsSuperAdminOnly]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        today = date.today()
        if not start:
            start = today.replace(day=1)
        if not end:
            end = today

        sales_qs = (
            Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(total=Sum("total"))
            .order_by("d")
        )

        exp_qs = (
            Expense.objects.filter(date__gte=start, date__lte=end)
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
@permission_classes([IsSuperAdminOnly])
def net_income_today(request):
    today = timezone.localdate()
    dec = DecimalField(max_digits=12, decimal_places=2)

    sales = (
        Order.objects
        .filter(is_paid=True, created_at__date=today)
        .aggregate(v=Coalesce(Sum(ORDER_TOTAL_FIELD), Value(0), output_field=dec))["v"]
    )

    expense = (
        Expense.objects
        .filter(date=today)
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
# API ViewSets (existing)
# =========================
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by("-id")
    serializer_class = CustomerSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by("-id")
    serializer_class = SupplierSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("name")
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        return {"request": self.request}

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by("-id")
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.select_related("category", "supplier", "unit").order_by("-id")

        category = self.request.query_params.get("category")
        if category and str(category).lower() not in ("all", "-1"):
            try:
                qs = qs.filter(category_id=int(category))
            except (ValueError, TypeError):
                pass

        search = self.request.query_params.get("search")
        if search:
            s = search.strip()
            if s:
                qs = qs.filter(
                    models.Q(name__icontains=s) |
                    models.Q(code__icontains=s) |
                    models.Q(sku__icontains=s)
                )
        return qs

    def get_serializer_context(self):
        return {"request": self.request}


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().order_by("-created_at")
    serializer_class = OrderSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().order_by("-date", "-time", "-id")
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]

class BannerViewSet(ModelViewSet):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer
    permission_classes = [AdminOnlyWriteOrRead]


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by("name")
    serializer_class = UnitSerializer
    permission_classes = [AdminOnlyWriteOrRead]

    def get_serializer_context(self):
        return {"request": self.request}

class InventoryCountViewSet(viewsets.ModelViewSet):
    queryset = InventoryCount.objects.all().order_by("-counted_at")
    serializer_class = InventoryCountSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(counted_by=self.request.user)

class ProductReturnViewSet(viewsets.ModelViewSet):
    queryset = ProductReturn.objects.prefetch_related("items").order_by("-returned_at", "-id")
    serializer_class = ProductReturnSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(returned_by=self.request.user)
        

class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMovement.objects.select_related(
        "product", "created_by"
    ).order_by("-created_at", "-id")

    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        product_id = self.request.query_params.get("product")
        mtype = self.request.query_params.get("type")

        if product_id:
            try:
                qs = qs.filter(product_id=int(product_id))
            except:
                pass

        if mtype:
            qs = qs.filter(movement_type=mtype)

        return qs

class StockAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = StockAdjustment.objects.all()
    serializer_class = StockAdjustmentSerializer
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def perform_create(self, serializer):
        adj = serializer.save(adjusted_by=self.request.user)

        product = adj.product
        before = product.stock
        after = adj.new_stock
        delta = after - before

        # Update stock
        Product.objects.filter(pk=product.pk).update(stock=after)

        # Create movement log
        StockMovement.objects.create(
            product=product,
            movement_type=StockMovement.Type.ADJUSTMENT,
            quantity_delta=delta,
            before_stock=before,
            after_stock=after,
            note=adj.reason,
            ref_model="StockAdjustment",
            ref_id=adj.id,
            created_by=self.request.user,
        )

# =========================
# Receipt PDF (xhtml2pdf)
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


def order_receipt_pdf(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related("items__product", "items__weight_unit").select_related("served_by"),
        id=order_id
    )
    shop = Shop.objects.first()

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
# GET /api/products/print-barcodes/?ids=1,2,3
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
    """
    Admin-only barcode printing (session-based, no DRF token needed).
    URL: /admin/print-barcodes/?ids=1,2,3
    """
    ids = (request.GET.get("ids") or "").strip()
    if not ids:
        return HttpResponse("Missing ids. Example: ?ids=1,2,3", status=400)

    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip()]
    except Exception:
        return HttpResponse("Invalid ids format. Example: ?ids=1,2,3", status=400)

    products = Product.objects.filter(id__in=id_list).order_by("name")

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
    # simple & stable
    # only admin can access: reports, settings, owner_chat
    perms = {
        "reports.view": bool(user.is_superuser),
        "settings.manage": bool(user.is_superuser),
        "owner_chat.use": bool(user.is_superuser),
    }
    # Convert to list of enabled codes for Android
    return [k for k, v in perms.items() if v]

@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    if not username or not password:
        return Response({"detail": "username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"detail": "Invalid credentials"}, status=401)

    token, _ = Token.objects.get_or_create(user=user)

    permissions = build_permissions_for_user(user)

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.get_username(),
            "full_name": getattr(user, "full_name", "") or "",
            "role": getattr(user, "role", "") or "",
            "is_staff": getattr(user, "is_staff", False),
            "is_superuser": getattr(user, "is_superuser", False),
        },
        "permissions": permissions
    }, status=200)

# =========================
# Shop API
# =========================
class ShopViewSet(viewsets.ModelViewSet):
    queryset = Shop.objects.all().order_by("-id")
    serializer_class = ShopSerializer
    permission_classes = [IsAuthenticated]