from django.shortcuts import render, redirect
from rest_framework import viewsets
from django.http import HttpResponse
from .models import Expense
from rest_framework.viewsets import ModelViewSet

from django.contrib.auth import authenticate
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes

from django.db.models.functions import TruncMonth
from django.db.models import Sum
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
    Order, OrderItem, Customer, Supplier, Product, Category, Unit, Banner
)
from .serializers import (
    OrderSerializer, CustomerSerializer, SupplierSerializer,
    ProductSerializer, CategorySerializer, UnitSerializer
)
from .decorators import role_required  # ✅ Dekorator for role-based access

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
    queryset = Product.objects.all().order_by('-id')
    serializer_class = ProductSerializer
    
    def get_serializer_context(self):
        return {'request': self.request}

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
                # hitung cart_items + total supaya halaman kasir tetap tampil lengkap
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
        'receipt_items': receipt_items,  # ✅ kirim list yang sudah benar
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

    labels = [d['month'].strftime('%B %Y') for d in data if d['month']]
    totals = [float(d['total']) for d in data if d['month']]

    context = _admin_context(request, "Expense Chart")
    context.update({'labels': labels, 'totals': totals})

    return _render_with_fallback(
        request,
        ["pos/expense_chart.html", "pos/expense_cart.html"],
        context
    )


# ✅ DIUBAH: tambahkan 'cashier'
@role_required(['admin', 'manager', 'cashier'])
def sales_chart_view(request):
    data = (
        OrderItem.objects
        .annotate(month=TruncMonth('order__created_at'))
        .values('month')
        .annotate(total=Sum('price'))
        .order_by('month')
    )

    labels = [d['month'].strftime('%B %Y') for d in data if d['month']]
    sales = [float(d['total']) for d in data if d['month']]

    total_order_price = sum(sales)
    total_tax = 0
    total_discount = 0
    net_sales = total_order_price - total_discount

    context = _admin_context(request, "Sales Chart")
    context.update({
        "labels": labels,
        "sales": sales,
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
    # ✅ Aman untuk JSON / form-data
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    # ✅ Validasi input biar jelas kalau request kosong
    if not username or not password:
        return Response(
            {"detail": "username dan password wajib diisi"},
            status=400
        )

    # ✅ Pakai request biar auth backend konsisten
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
