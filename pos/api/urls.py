from django.urls import path

from pos.api.views_shift import (
    ShiftCurrentView, ShiftOpenView, ShiftCloseView,
    ShiftListView, ShiftReportView
)

from pos.api.views_finance import FinanceSummaryAPIView

urlpatterns = [
    path("shifts/current/", ShiftCurrentView.as_view()),
    path("shifts/open/", ShiftOpenView.as_view()),
    path("shifts/close/", ShiftCloseView.as_view()),
    path("shifts/", ShiftListView.as_view()),
    path("shifts/<int:pk>/report/", ShiftReportView.as_view()),

    # ✅ NEW: Finance Summary JSON
    path("finance/summary/", FinanceSummaryAPIView.as_view()),
]