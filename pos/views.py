from django.shortcuts import render, redirect
from rest_framework import viewsets
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from pos.models import Order, Expense
from rest_framework.permissions import IsAuthenticated
from .serializers import ExpenseSerializer
from django.http import HttpResponse
from .models import Expense
from rest_framework.viewsets import ModelViewSet

from datetime import datetime, date
from django.utils.dateparse import parse_date
from django.db.models.functions import TruncDate, TruncMonth
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.contrib.auth import authenticate
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes

from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncMonth
import json

from django.db import models
from .models import Shop
from django.template.loader import get_template
from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import BannerSerializer
from .models import Banner
import io
from xhtml2pdf import pisa
from django.shortcuts import get_object_or_404
from .models import (
    Order, OrderItem, Customer, Supplier, Product, Category, Unit, Banner, Shop
)
from .serializers import (
    OrderSerializer, CustomerSerializer, SupplierSerializer,
    ProductSerializer, CategorySerializer, UnitSerializer, ShopSerializer
)
from .decorators import role_required

# ✅ TAMBAH: untuk context admin Jazzmin
from django.contrib import admin as django_admin

from django.template import TemplateDoesNotExist


# API ViewSets
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by('-id')
    serializer_class = CustomerSerializer


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by('-id')
    serializer_class = SupplierSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by('name')
    serializer_class = CategorySerializer

    def get_serializer_context(self):
        return {'request': self.request}


class UnitViewSet(viewsets.ModelViewSet):
    queryset = Unit.objects.all().order_by('name')
    serializer_class = UnitSerializer


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
                qs = qs.filter(models.Q(name__icontains=s) | models.Q(code__icontains=s))

        return qs

    def get_serializer_context(self):
        return {"request": self.request}


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().order_by('-created_at')
    serializer_class = OrderSerializer


# ✅ Helper: supaya semua report selalu “nyatu” dengan Jazzmin
def _admin_context(request, title: str):
    ctx = django_admin.site.each_context(request)
    ctx["title"] = title
    return ctx


# ✅ Helper: render template dengan fallback (kalau nama file template berbeda)
def _render_with_fallback(request, templates, context):
    """
    templates: list template candidates, contoh:
      ["pos/expense_chart.html", "pos/expense_cart.html"]
    """
    last_err = None
    for tpl in templates:
        try:
            return render(request, tpl, context)
        except TemplateDoesNotExist as e:
            last_err = e
            continue
    raise last_err


# View normal ho asesu espesífiku role
@role_required(['admin', 'manager', 'cashier'])
def sales_report_view(request):
    month = request.GET.get('month')
    rows = []

    items = OrderItem.objects.select_related('order', 'product', 'weight_unit')

    if month:
        year, month_number = month.split("-")
        items = items.filter(order__created_at__year=year, order__created_at__month=month_number)

    for item in items:
        rows.append({
            'product_name': item.product.name,
            'invoice_id': f"INV{item.order.id:015d}",
            'qty': item.quantity,
            'weight': f"{item.product.weight} {item.weight_unit.name}" if item.weight_unit else "-",
            'total_price': item.quantity * item.price,
            'order_date': item.order.created_at.strftime("%d %B, %Y"),
        })

    context = _admin_context(request, "Sales Report")
    context.update({'rows': rows})
    return render(request, 'pos/sales_report.html', context)


def pos_kasir_view(request):
    return render(request, 'pos/pos_kasir.html')


# NOTE: ini duplicate dengan fungsi di atas, sesuai permintaan kamu saya tidak hapus.
# Python akan memakai definisi yang terakhir ini.
def pos_kasir_view(request):
    from .models import Product

    products = Product.objects.all()
    cart = request.session.get('cart', [])

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        quantity = int(request.POST.get('quantity', 1))

        for item in cart:
            if item['product_id'] == product_id:
                item['quantity'] += quantity
                break
        else:
            cart.append({'product_id': product_id, 'quantity': quantity})

        request.session['cart'] = cart
        return redirect('pos_kasir')

    cart_items = []
    total = 0
    for item in cart:
        product = Product.objects.get(id=item['product_id'])
        subtotal = product.sell_price * item['quantity']
        total += subtotal
        cart_items.append({
            'product': product,
            'quantity': item['quantity'],
            'subtotal': subtotal
        })

    return render(request, 'pos/pos_kasir.html', {
        'products': products,
        'cart_items': cart_items,
        'total': total
    })


def pos_remove_from_cart(request, product_id):
    cart = request.session.get('cart', [])
    cart = [item for item in cart if item['product_id'] != str(product_id)]
    request.session['cart'] = cart
    return redirect('pos_kasir')


def pos_checkout(request):
    from .models import Order, OrderItem, Product, Customer

    cart = request.session.get('cart', [])
    if not cart:
        return redirect('pos_kasir')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')

        order = Order.objects.create(
            customer=None,
            payment_method=payment_method,
            subtotal=0,
            discount=0,
            tax=0,
            total=0,
            notes="",
            served_by=request.user,
            is_paid=True
        )

        subtotal = 0
        for item in cart:
            product = Product.objects.get(id=item['product_id'])
            quantity = item['quantity']

            # ✅ VALIDASI HARGA (WAJIB) — stop checkout kalau harga belum di-set
            if product.sell_price <= 0:
                products = Product.objects.all()
                cart_items = []
                total = 0
                for c in cart:
                    p = Product.objects.get(id=c['product_id'])
                    sub = p.sell_price * c['quantity']
                    total += sub
                    cart_items.append({
                        'product': p,
                        'quantity': c['quantity'],
                        'subtotal': sub
                    })

                return render(request, 'pos/pos_kasir.html', {
                    'products': products,
                    'cart_items': cart_items,
                    'total': total,
                    'error': f"Harga produk '{product.name}' belum di-set. Hubungi admin."
                })

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                price=product.sell_price,
                weight_unit=product.unit
            )
            product.stock -= quantity
            product.save()
            subtotal += product.sell_price * quantity

        tax = 0
        discount = 0
        total = subtotal + tax - discount

        order.subtotal = subtotal
        order.tax = tax
        order.discount = discount
        order.total = total
        order.save()

        request.session['cart'] = []
        return redirect('pos_kasir')

    return redirect('pos_kasir')


def order_receipt_pdf(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product', 'items__weight_unit').select_related('served_by'),
        id=order_id
    )
    shop = Shop.objects.first()

    # ✅ hitung aman (pakai price yang tersimpan di OrderItem)
    receipt_items = []
    for item in order.items.all():
        unit_price = item.price or 0
        line_total = (item.quantity or 0) * unit_price

        receipt_items.append({
            "name": item.product.name if item.product else "-",
            "qty": item.quantity or 0,
            "unit_price": unit_price,
            "line_total": line_total,
        })

    template = get_template('pos/order_receipt.html')
    html = template.render({
        'order': order,
        'shop': shop,
        'receipt_items': receipt_items,
    })

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)

    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    else:
        return HttpResponse('Error generating PDF', status=500)


# ✅ DIUBAH: tambahkan 'cashier' supaya tidak redirect ke dashboard
@role_required(['admin', 'manager', 'cashier'])
def expense_report_view(request):
    expenses = Expense.objects.all().order_by('-date', '-time')
    context = _admin_context(request, "Expense Report")
    context.update({'expenses': expenses})
    return render(request, 'pos/expense_report.html', context)


# ✅ DIUBAH: tambahkan 'cashier'
@role_required(['admin', 'manager', 'cashier'])
def expense_chart_view(request):
    data = (
        Expense.objects
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    labels_list = [d['month'].strftime('%B %Y') for d in data if d.get('month')]
    totals_list = [float(d.get('total') or 0) for d in data if d.get('month')]

    context = _admin_context(request, "Expense Chart")
    # ✅ kirim JSON agar aman untuk Chart.js
    context.update({
        'labels': json.dumps(labels_list),
        'totals': json.dumps(totals_list),
    })

    return _render_with_fallback(
        request,
        ["pos/expense_chart.html", "pos/expense_cart.html"],
        context
    )


# ✅ DIUBAH: tambahkan 'cashier'
@role_required(['admin', 'manager', 'cashier'])
def sales_chart_view(request):
    # 1) Hitung line_total = price * quantity
    line_total = ExpressionWrapper(
        F("price") * F("quantity"),
        output_field=DecimalField(max_digits=12, decimal_places=2)
    )

    # 2) Grouping per bulan, lalu jumlahkan line_total
    data = (
        OrderItem.objects
        .filter(order__is_paid=True)  # hanya transaksi PAID
        .annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(total_sales=Sum(line_total))
        .order_by("month")
    )

    # 3) Siapkan labels & sales untuk chart
    labels_list = [d["month"].strftime("%B %Y") for d in data if d.get("month")]
    sales_list = [float(d.get("total_sales") or 0) for d in data if d.get("month")]

    # 4) Hitung card summary
    total_order_price = float(sum(sales_list))
    total_tax = 0.0
    total_discount = 0.0
    net_sales = total_order_price - total_discount + total_tax

    # 5) context untuk template + aman untuk JS (json.dumps)
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
    

class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all().order_by("-date", "-time", "-id")
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated]    

class BannerListView(APIView):
    def get(self, request):
        banners = Banner.objects.all()
        serializer = BannerSerializer(banners, many=True, context={'request': request})
        return Response(serializer.data)


class BannerViewSet(ModelViewSet):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    if not username or not password:
        return Response(
            {"detail": "username dan password wajib diisi"},
            status=400
        )

    user = authenticate(request, username=username, password=password)
    if not user:
        return Response(
            {"detail": "Username atau password salah"},
            status=401
        )

    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.get_username(),
            "full_name": getattr(user, "full_name", "") or "",
            "role": getattr(user, "role", "") or "",
            "is_staff": getattr(user, "is_staff", False),
            "is_superuser": getattr(user, "is_superuser", False),
        }
    }, status=200)


class ShopViewSet(viewsets.ModelViewSet):
    queryset = Shop.objects.all().order_by("-id")
    serializer_class = ShopSerializer

    def get_serializer_context(self):
        return {"request": self.request}

class DailyProfitReportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")

        # default: bulan ini (aman)
        today = date.today()
        if not start:
            start = today.replace(day=1)
        if not end:
            end = today

        # SALES per hari (pakai Order.total)
        sales_qs = (
            Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(total=Sum("total"))
            .order_by("d")
        )

        # EXPENSE per hari
        exp_qs = (
            Expense.objects.filter(date__gte=start, date__lte=end)
            .values("date")
            .annotate(total=Sum("amount"))
            .order_by("date")
        )

        sales_map = {row["d"]: float(row["total"] or 0) for row in sales_qs}
        exp_map = {row["date"]: float(row["total"] or 0) for row in exp_qs}

        # gabung semua tanggal yang ada di salah satu map
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


class MonthlyPLReportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start = parse_date(request.GET.get("start") or "")
        end = parse_date(request.GET.get("end") or "")
        today = date.today()

        # default: 12 bulan terakhir (sederhana)
        if not start:
            start = date(today.year, 1, 1)
        if not end:
            end = date(today.year, 12, 31)

        sales_qs = (
            Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
            .annotate(m=TruncMonth("created_at"))
            .values("m")
            .annotate(total=Sum("total"))
            .order_by("m")
        )

        exp_qs = (
            Expense.objects.filter(date__gte=start, date__lte=end)
            .annotate(m=TruncMonth("date"))
            .values("m")
            .annotate(total=Sum("amount"))
            .order_by("m")
        )

        sales_map = {row["m"]: float(row["total"] or 0) for row in sales_qs}
        exp_map = {row["m"]: float(row["total"] or 0) for row in exp_qs}

        all_months = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

        rows = []
        total_sales = 0.0
        total_exp = 0.0

        for m in all_months:
            s = float(sales_map.get(m, 0))
            e = float(exp_map.get(m, 0))
            p = s - e
            total_sales += s
            total_exp += e
            rows.append({
                "month": m.strftime("%Y-%m"),
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
        
@role_required(['admin', 'manager', 'cashier'])
def daily_profit_dashboard_view(request):
    # default: 14 hari terakhir
    from datetime import timedelta
    from django.utils.timezone import now
    from django.utils.dateparse import parse_date
    import json

    start = parse_date(request.GET.get("start") or "")
    end = parse_date(request.GET.get("end") or "")

    today = now().date()
    if not end:
        end = today
    if not start:
        start = end - timedelta(days=13)

    # SALES per hari (Order.total)
    sales_qs = (
        Order.objects.filter(is_paid=True, created_at__date__gte=start, created_at__date__lte=end)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(total=Sum("total"))
        .order_by("d")
    )

    # EXPENSE per hari
    exp_qs = (
        Expense.objects.filter(date__gte=start, date__lte=end)
        .values("date")
        .annotate(total=Sum("amount"))
        .order_by("date")
    )

    sales_map = {row["d"]: float(row["total"] or 0) for row in sales_qs}
    exp_map = {row["date"]: float(row["total"] or 0) for row in exp_qs}

    all_days = sorted(set(list(sales_map.keys()) + list(exp_map.keys())))

    labels = []
    sales = []
    expense = []
    profit = []

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

@role_required(['admin', 'manager', 'cashier'])
def monthly_pl_dashboard_view(request):
    import json
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

@api_view(["GET"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def net_income_today(request):
    today = timezone.localdate()

    dec = DecimalField(max_digits=12, decimal_places=2)

    # ✅ SALES (paid only)
    sales = (
        Order.objects
        .filter(is_paid=True, created_at__date=today)
        .aggregate(v=Coalesce(Sum("total"), Value(0), output_field=dec))["v"]
    )

    # ✅ EXPENSE (use Expense.date)
    expense = (
        Expense.objects
        .filter(date=today)
        .aggregate(v=Coalesce(Sum("amount"), Value(0), output_field=dec))["v"]
    )

    net_income = sales - expense

    return Response({
        "date": str(today),
        "sales": float(sales),
        "expense": float(expense),
        "net_income": float(net_income),
    })
