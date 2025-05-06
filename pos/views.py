from django.shortcuts import render, redirect
from rest_framework import viewsets
from django.http import HttpResponse
from .models import Expense
from rest_framework.viewsets import ModelViewSet

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

    context = {
        'rows': rows
    }
    return render(request, 'pos/sales_report.html', context)


def pos_kasir_view(request):
    return render(request, 'pos/pos_kasir.html')

def pos_kasir_view(request):
    from .models import Product

    products = Product.objects.all()
    cart = request.session.get('cart', [])

    if request.method == 'POST':
        # Aumenta ba karosa kompra
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

    # Hamosu produtu hotu-hotu iha karosa kompra
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
            customer=None,  # Depois bele hili kliente
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

        tax = 0  # bele halo 10% karik bele aumenta
        discount = 0
        total = subtotal + tax - discount

        order.subtotal = subtotal
        order.tax = tax
        order.discount = discount
        order.total = total
        order.save()

        # Hamamuk karosa kompra
        request.session['cart'] = []

        return redirect('pos_kasir')

    return redirect('pos_kasir')

def order_receipt_pdf(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'served_by'), id=order_id)
    shop = Shop.objects.first()  # Foti informasaun loja

    template = get_template('pos/order_receipt.html')
    html = template.render({'order': order, 'shop': shop})

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), result)

    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type='application/pdf')
    else:
        return HttpResponse('Error generating PDF', status=500)
    

@role_required(['admin', 'manager'])
def expense_report_view(request):
    expenses = Expense.objects.all().order_by('-date', '-time')
    return render(request, 'pos/expense_report.html', {'expenses': expenses})

# ➔ Expense Chart (Gráfiku gastu mensál)
@role_required(['admin', 'manager'])
def expense_chart_view(request):
    data = (
        Expense.objects
        .annotate(month=TruncMonth('date'))  # Grupu tuir fulan
        .values('month')
        .annotate(total=Sum('amount'))
        .order_by('month')
    )

    labels = [d['month'].strftime('%B %Y') for d in data]
    totals = [float(d['total']) for d in data]

    return render(request, 'pos/expense_chart.html', {
        'labels': labels,
        'totals': totals
    })    
    

class BannerListView(APIView):
    def get(self, request):
        banners = Banner.objects.all()
        serializer = BannerSerializer(banners, many=True, context={'request': request})
        return Response(serializer.data)
    
class BannerViewSet(ModelViewSet):
    queryset = Banner.objects.all()
    serializer_class = BannerSerializer    