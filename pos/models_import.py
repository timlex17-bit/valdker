# pos/models_import.py

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# ==========================================================
# BASE MIXIN
# ==========================================================
class CleanSaveMixin:
    """
    Production-safe save:
    - run model validation before save
    """
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


# ==========================================================
# HELPERS
# ==========================================================
def import_file_upload_to(instance, filename: str) -> str:
    shop_code = "unknown-shop"
    if getattr(instance, "shop", None) and getattr(instance.shop, "code", None):
        shop_code = str(instance.shop.code).strip().upper()

    filename = os.path.basename(filename or "master_import.xlsx")
    return f"imports/{shop_code}/{filename}"


# ==========================================================
# IMPORT JOB
# ==========================================================
class ImportJob(CleanSaveMixin, models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        VALIDATED = "validated", "Validated"
        IMPORTING = "importing", "Importing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="import_jobs"
    )

    file = models.FileField(upload_to=import_file_upload_to)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size_bytes = models.BigIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADED,
        db_index=True
    )

    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)

    imported_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)

    note = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_import_jobs"
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Import Job"
        verbose_name_plural = "Import Jobs"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=["shop", "status"]),
            models.Index(fields=["shop", "created_at"]),
            models.Index(fields=["shop", "validated_at"]),
            models.Index(fields=["shop", "completed_at"]),
        ]

    def clean(self):
        self.original_filename = (self.original_filename or "").strip()
        self.note = (self.note or "").strip()
        self.error_message = (self.error_message or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.file_size_bytes < 0:
            raise ValidationError({"file_size_bytes": "File size cannot be negative."})

        if self.uploaded_by_id and self.uploaded_by and not self.uploaded_by.is_superuser:
            if self.uploaded_by.shop_id != self.shop_id:
                raise ValidationError({"uploaded_by": "User must belong to the same shop."})

        if self.valid_rows + self.invalid_rows > self.total_rows and self.total_rows > 0:
            raise ValidationError({
                "invalid_rows": "Valid rows plus invalid rows cannot exceed total rows."
            })

    @property
    def status_label(self):
        return self.get_status_display()

    def mark_uploaded(self):
        self.status = self.Status.UPLOADED
        self.validated_at = None
        self.completed_at = None
        self.error_message = ""
        self.save()

    def mark_validated(self, *, total_rows=0, valid_rows=0, invalid_rows=0, note="", metadata=None):
        self.status = self.Status.VALIDATED
        self.total_rows = int(total_rows or 0)
        self.valid_rows = int(valid_rows or 0)
        self.invalid_rows = int(invalid_rows or 0)
        self.validated_at = timezone.now()
        self.note = (note or self.note or "").strip()
        self.error_message = ""
        if metadata is not None:
            self.metadata = metadata
        self.save()

    def mark_importing(self):
        self.status = self.Status.IMPORTING
        self.error_message = ""
        self.save(update_fields=["status", "error_message"])

    def mark_completed(self, *, imported_rows=0, skipped_rows=0, note="", metadata=None):
        self.status = self.Status.COMPLETED
        self.imported_rows = int(imported_rows or 0)
        self.skipped_rows = int(skipped_rows or 0)
        self.completed_at = timezone.now()
        self.note = (note or self.note or "").strip()
        self.error_message = ""
        if metadata is not None:
            self.metadata = metadata
        self.save()

    def mark_failed(self, error_message: str, *, note=""):
        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.error_message = (error_message or "").strip()
        if note:
            self.note = (note or "").strip()
        self.save()

    def __str__(self):
        return f"{self.shop.code} - Import #{self.id} - {self.get_status_display()}"


# ==========================================================
# IMPORT ROW ERROR
# ==========================================================
class ImportRowError(CleanSaveMixin, models.Model):
    import_job = models.ForeignKey(
        "ImportJob",
        on_delete=models.CASCADE,
        related_name="row_errors"
    )

    sheet_name = models.CharField(max_length=100)
    row_number = models.PositiveIntegerField()
    field_name = models.CharField(max_length=100, blank=True, default="")
    message = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Import Row Error"
        verbose_name_plural = "Import Row Errors"
        ordering = ("sheet_name", "row_number", "id")
        indexes = [
            models.Index(fields=["import_job", "sheet_name"]),
            models.Index(fields=["import_job", "row_number"]),
        ]

    def clean(self):
        self.sheet_name = (self.sheet_name or "").strip()
        self.field_name = (self.field_name or "").strip()
        self.message = (self.message or "").strip()

        if not self.import_job_id:
            raise ValidationError({"import_job": "Import job is required."})

        if not self.sheet_name:
            raise ValidationError({"sheet_name": "Sheet name is required."})

        if self.row_number < 1:
            raise ValidationError({"row_number": "Row number must be at least 1."})

        if not self.message:
            raise ValidationError({"message": "Error message is required."})

    def __str__(self):
        field_part = f" [{self.field_name}]" if self.field_name else ""
        return f"{self.sheet_name} row {self.row_number}{field_part}: {self.message}"