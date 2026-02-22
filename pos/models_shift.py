from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Value, DecimalField

DEC0 = Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))

class ShiftStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"

class Shift(models.Model):
    shop = models.ForeignKey("pos.Shop", on_delete=models.CASCADE, related_name="shifts")  # kalau Anda ada Shop
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shifts")

    status = models.CharField(max_length=10, choices=ShiftStatus.choices, default=ShiftStatus.OPEN)

    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    opening_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    closing_cash = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    # Totals (snapshot / cached)
    total_sales = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_refunds = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    total_expenses = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    expected_cash = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    cash_difference = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["shop", "status", "opened_at"]),
            models.Index(fields=["cashier", "status", "opened_at"]),
        ]

    def __str__(self):
        return f"Shift#{self.id} {self.shop_id} {self.cashier_id} {self.status}"