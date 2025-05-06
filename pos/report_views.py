from django.shortcuts import render
from django.db.models import Sum
from .models import Expense
from django.http import HttpResponse
import openpyxl
import json
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404
from xhtml2pdf import pisa
from django.db.models.functions import TruncMonth
from django.template.loader import get_template
from django.utils.timezone import localtime
import io
import tempfile
from .models import OrderItem
from django.db.models import F
from .models import Order, OrderItem
from django.db.models.functions import TruncMonth

def expense_chart_view(request):
    data = (
        Expense.objects
        .annotate(month=TruncMonth('date'))
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

def sales_export_view(request):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Report"

    # Header
    headers = [
        "Transaction ID", "Date", "Customer", "Product",
        "Qty", "Price", "Subtotal", "Discount", "Tax", "Total"
    ]
    ws.append(headers)

    # Data rows
    orders = Order.objects.prefetch_related("items", "customer")

    for order in orders:
        for item in order.items.all():
            ws.append([
                f"ORDER-{order.id}",
                order.created_at.strftime("%Y-%m-%d %H:%M"),
                order.customer.name if order.customer else "-",
                item.product.name,
                item.quantity,
                item.price,
                item.quantity * item.price,
                order.discount,
                order.tax,
                order.total
            ])

    # Response
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=sales_report.xlsx"
    wb.save(response)
    return response

def order_pdf_view(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("items__product"), id=order_id)
    template = get_template("pos/order_receipt.html")
    html = template.render({"order": order})

    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)

    if not pdf.err:
        return HttpResponse(result.getvalue(), content_type="application/pdf")
    else:
        return HttpResponse("PDF generation error", status=500)


def sales_chart_view(request):
    orders = Order.objects.annotate(month=TruncMonth('created_at')).order_by('month')

    data = (
        orders.values('month')
        .annotate(
            total_sales=Sum('total'),
            total_discount=Sum('discount'),
            total_tax=Sum('tax'),
        )
    )

    labels = [d['month'].strftime('%b') for d in data]
    sales = [float(d['total_sales']) for d in data]
    discounts = [float(d['total_discount']) for d in data]
    taxes = [float(d['total_tax']) for d in data]

    total_order_price = sum(sales)
    total_discount = sum(discounts)
    total_tax = sum(taxes)
    net_sales = total_order_price - total_discount + total_tax

    return render(request, 'pos/sales_chart.html', {
        'labels': labels,
        'sales': sales,
        'total_order_price': total_order_price,
        'total_discount': total_discount,
        'total_tax': total_tax,
        'net_sales': net_sales
    })
    
    
def expense_report_view(request):
    expenses = Expense.objects.all().order_by('-date', '-time')
    return render(request, 'pos/expense_report.html', {'expenses': expenses})

def sales_report_view(request):
    month = request.GET.get('month')
    rows = []

    # Prefetch benar: items, product di dalam items, weight_unit di dalam items
    orders = Order.objects.prefetch_related('items', 'items__product', 'items__weight_unit')

    if month:
        try:
            year, month_number = map(int, month.split('-'))
            orders = orders.filter(created_at__year=year, created_at__month=month_number)
        except ValueError:
            pass  # kalau user salah input, abaikan filter

    for order in orders:
        for item in order.items.all():
            rows.append({
                'product_name': item.product.name,
                'invoice_id': f"ORDER-{order.id}",
                'qty': item.quantity,
                'weight': item.weight_unit.name if item.weight_unit else "-",
                'total_price': item.quantity * item.price,
                'order_date': order.created_at.strftime("%Y-%m-%d"),
            })

    context = {
        'rows': rows
    }
    return render(request, 'pos/sales_report.html', context)
    
def sales_report_pdf_view(request):
    month = request.GET.get('month')
    orders = Order.objects.all()

    if month:
        year, month = map(int, month.split("-"))
        orders = orders.filter(created_at__year=year, created_at__month=month)

    html = render_to_string("pos/sales_report_pdf.html", {'orders': orders})
    result = io.BytesIO()
    pisa.CreatePDF(io.BytesIO(html.encode("UTF-8")), dest=result)

    return HttpResponse(result.getvalue(), content_type='application/pdf')

def sales_report_excel_view(request):
    month = request.GET.get('month')
    orders = Order.objects.prefetch_related("items", "customer")

    if month:
        year, month = map(int, month.split("-"))
        orders = orders.filter(created_at__year=year, created_at__month=month)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Report"

    headers = ["Product Name", "Invoice ID", "Qty", "Weight", "Total Price", "Order Date"]
    ws.append(headers)

    for order in orders:
        for item in order.items.all():
            ws.append([
                item.product.name,
                f"ORDER-{order.id}",
                item.quantity,
                item.weight_unit.name if item.weight_unit else '',
                item.quantity * item.price,
                order.created_at.strftime("%Y-%m-%d %H:%M")
            ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response['Content-Disposition'] = 'attachment; filename=sales_report.xlsx'
    wb.save(response)
    return response

def sales_report_print_view(request):
    month = request.GET.get("month")
    orders = Order.objects.all()

    if month:
        year, month = map(int, month.split('-'))
        orders = orders.filter(created_at__year=year, created_at__month=month)

    rows = []
    for order in orders:
        for item in order.items.all():
            rows.append({
                "product_name": item.product.name,
                "invoice_id": f"ORDER-{order.id}",
                "qty": item.quantity,
                "weight": item.weight_unit.name if item.weight_unit else "",
                "total_price": item.quantity * item.price,
                "order_date": order.created_at.date()
            })

    return render(request, "pos/sales_report_print.html", {"rows": rows})    