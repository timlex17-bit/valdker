from django.urls import path

from pos import views
from . import report_views

urlpatterns = [
    path('expense-chart/', report_views.expense_chart_view, name='expense_chart'),
    path('sales-export/', report_views.sales_export_view, name='sales_export'),
    path('order/<int:order_id>/pdf/', report_views.order_pdf_view, name='order_pdf'),
    path('sales-chart/', report_views.sales_chart_view, name='sales_chart'),
    path('expense/', report_views.expense_report_view, name='expense_report'),
    path('sales/', report_views.sales_report_view, name='sales_report'),
    path('sales/pdf/', report_views.sales_report_pdf_view, name='sales_report_pdf'),
    path('sales/excel/', report_views.sales_report_excel_view, name='sales_report_excel'),
    path("sales/print/", report_views.sales_report_print_view, name="sales_report_print"),
    path('daily-profit/', views.daily_profit_dashboard_view, name='daily_profit_dashboard'),
    path('monthly-pl/', views.monthly_pl_dashboard_view, name='monthly_pl_dashboard'),
]