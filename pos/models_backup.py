# pos/models_backup.py

import os
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
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
def backup_file_upload_to(instance, filename: str) -> str:
    """
    Simpan file backup per shop agar rapi:
    media/backups/<SHOP_CODE>/filename.zip
    """
    shop_code = "unknown-shop"
    if getattr(instance, "shop", None) and getattr(instance.shop, "code", None):
        shop_code = str(instance.shop.code).strip().upper()

    filename = os.path.basename(filename or "backup.zip")
    return f"backups/{shop_code}/{filename}"


def restore_file_upload_to(instance, filename: str) -> str:
    """
    Kalau nanti support upload file restore manual.
    """
    shop_code = "unknown-shop"
    if getattr(instance, "shop", None) and getattr(instance.shop, "code", None):
        shop_code = str(instance.shop.code).strip().upper()

    filename = os.path.basename(filename or "restore.zip")
    return f"backups/{shop_code}/restore_uploads/{filename}"


# ==========================================================
# BACKUP SETTINGS (1 row per shop)
# ==========================================================
class BackupSetting(CleanSaveMixin, models.Model):
    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    class RestoreMode(models.TextChoices):
        FULL = "full", "Full Restore"
        MASTER = "master", "Master Data Only"

    shop = models.OneToOneField(
        "Shop",
        on_delete=models.CASCADE,
        related_name="backup_setting"
    )

    enabled = models.BooleanField(default=True)

    frequency = models.CharField(
        max_length=20,
        choices=Frequency.choices,
        default=Frequency.DAILY,
        db_index=True
    )
    backup_time = models.TimeField(default="23:30")
    keep_last = models.PositiveIntegerField(default=10)

    include_media = models.BooleanField(default=True)
    include_users = models.BooleanField(default=True)
    include_settings = models.BooleanField(default=True)

    default_restore_mode = models.CharField(
        max_length=20,
        choices=RestoreMode.choices,
        default=RestoreMode.FULL
    )

    last_auto_backup_at = models.DateTimeField(null=True, blank=True)
    last_manual_backup_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Backup Setting"
        verbose_name_plural = "Backup Settings"
        indexes = [
            models.Index(fields=["enabled", "frequency"]),
        ]

    def clean(self):
        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.keep_last < 1:
            raise ValidationError({"keep_last": "Keep last backup must be at least 1."})

    @property
    def auto_backup_status_label(self):
        return "Enabled" if self.enabled else "Disabled"

    def __str__(self):
        return f"Backup Settings - {self.shop.name}"


# ==========================================================
# BACKUP HISTORY
# ==========================================================
class BackupHistory(CleanSaveMixin, models.Model):
    class BackupType(models.TextChoices):
        AUTO = "auto", "Auto"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RUNNING = "running", "Running"

    class RestoreMode(models.TextChoices):
        FULL = "full", "Full Restore"
        MASTER = "master", "Master Data Only"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="backup_histories"
    )

    backup_type = models.CharField(
        max_length=20,
        choices=BackupType.choices,
        default=BackupType.MANUAL,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True
    )

    triggered_by = models.CharField(max_length=150, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_backup_histories"
    )

    # isi backup
    include_database = models.BooleanField(default=True)
    include_media = models.BooleanField(default=False)
    include_users = models.BooleanField(default=False)
    include_settings = models.BooleanField(default=False)

    # file metadata
    file_name = models.CharField(max_length=255, blank=True, default="")
    file = models.FileField(
        upload_to=backup_file_upload_to,
        null=True,
        blank=True
    )
    file_size_bytes = models.BigIntegerField(default=0)
    file_size_label = models.CharField(max_length=50, blank=True, default="")
    file_checksum = models.CharField(max_length=128, blank=True, default="")

    # audit
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # info tambahan
    note = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Backup History"
        verbose_name_plural = "Backup Histories"
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=["shop", "status"]),
            models.Index(fields=["shop", "backup_type"]),
            models.Index(fields=["shop", "started_at"]),
            models.Index(fields=["shop", "completed_at"]),
        ]

    def clean(self):
        self.triggered_by = (self.triggered_by or "").strip()
        self.file_name = (self.file_name or "").strip()
        self.file_size_label = (self.file_size_label or "").strip()
        self.file_checksum = (self.file_checksum or "").strip()
        self.note = (self.note or "").strip()
        self.error_message = (self.error_message or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if self.file_size_bytes < 0:
            raise ValidationError({"file_size_bytes": "File size cannot be negative."})

        if self.completed_at and self.completed_at < self.started_at:
            raise ValidationError({
                "completed_at": "Completed time cannot be earlier than started time."
            })

        if self.created_by_id and self.created_by and not self.created_by.is_superuser:
            if self.created_by.shop_id != self.shop_id:
                raise ValidationError({
                    "created_by": "User must belong to the same shop."
                })

        if self.status == self.Status.SUCCESS and not self.file_name:
            raise ValidationError({
                "file_name": "Successful backup must have a file name."
            })

        if self.status == self.Status.SUCCESS and not self.completed_at:
            raise ValidationError({
                "completed_at": "Successful backup must have completed_at."
            })

        if self.status == self.Status.FAILED and not self.error_message:
            raise ValidationError({
                "error_message": "Failed backup should store an error message."
            })

    @property
    def type_label(self):
        return self.get_backup_type_display()

    @property
    def status_label(self):
        return self.get_status_display()

    @property
    def is_success(self):
        return self.status == self.Status.SUCCESS

    @property
    def is_failed(self):
        return self.status == self.Status.FAILED

    @property
    def is_running(self):
        return self.status == self.Status.RUNNING

    @property
    def included_items(self):
        items = ["Database"]
        if self.include_media:
            items.append("Media")
        if self.include_users:
            items.append("Users")
        if self.include_settings:
            items.append("Settings")
        return items

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.completed_at = None
        self.error_message = ""
        self.save(update_fields=["status", "started_at", "completed_at", "error_message"])

    def mark_success(
        self,
        *,
        file_name: str = "",
        file_size_bytes: int = 0,
        file_size_label: str = "",
        checksum: str = "",
        note: str = "",
        metadata: dict | None = None,
    ):
        self.status = self.Status.SUCCESS
        self.completed_at = timezone.now()
        self.file_name = (file_name or self.file_name or "").strip()
        self.file_size_bytes = max(0, int(file_size_bytes or 0))
        self.file_size_label = (file_size_label or "").strip()
        self.file_checksum = (checksum or "").strip()
        self.note = (note or self.note or "").strip()
        if metadata is not None:
            self.metadata = metadata
        self.error_message = ""
        self.save()

    def mark_failed(self, error_message: str, *, note: str = ""):
        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.error_message = (error_message or "").strip()
        if note:
            self.note = (note or "").strip()
        self.save()

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def __str__(self):
        return f"{self.shop.code} - {self.get_backup_type_display()} - {self.started_at:%Y-%m-%d %H:%M}"


# ==========================================================
# RESTORE HISTORY
# ==========================================================
class RestoreHistory(CleanSaveMixin, models.Model):
    class RestoreMode(models.TextChoices):
        FULL = "full", "Full Restore"
        MASTER = "master", "Master Data Only"

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RUNNING = "running", "Running"

    shop = models.ForeignKey(
        "Shop",
        on_delete=models.CASCADE,
        related_name="restore_histories"
    )

    backup = models.ForeignKey(
        "BackupHistory",
        on_delete=models.CASCADE,
        related_name="restore_histories"
    )

    restore_mode = models.CharField(
        max_length=20,
        choices=RestoreMode.choices,
        default=RestoreMode.FULL,
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True
    )

    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_restores"
    )
    triggered_by = models.CharField(max_length=150, blank=True, default="")

    restore_file = models.FileField(
        upload_to=restore_file_upload_to,
        null=True,
        blank=True
    )

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    note = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Restore History"
        verbose_name_plural = "Restore Histories"
        ordering = ("-started_at", "-id")
        indexes = [
            models.Index(fields=["shop", "status"]),
            models.Index(fields=["shop", "restore_mode"]),
            models.Index(fields=["shop", "started_at"]),
        ]

    def clean(self):
        self.triggered_by = (self.triggered_by or "").strip()
        self.note = (self.note or "").strip()
        self.error_message = (self.error_message or "").strip()

        if not self.shop_id:
            raise ValidationError({"shop": "Shop is required."})

        if not self.backup_id:
            raise ValidationError({"backup": "Backup is required."})

        if self.backup_id and self.shop_id and self.backup.shop_id != self.shop_id:
            raise ValidationError({
                "backup": "Backup must belong to the same shop."
            })

        if self.restored_by_id and self.restored_by and not self.restored_by.is_superuser:
            if self.restored_by.shop_id != self.shop_id:
                raise ValidationError({
                    "restored_by": "User must belong to the same shop."
                })

        if self.completed_at and self.completed_at < self.started_at:
            raise ValidationError({
                "completed_at": "Completed time cannot be earlier than started time."
            })

        if self.status == self.Status.SUCCESS and not self.completed_at:
            raise ValidationError({
                "completed_at": "Successful restore must have completed_at."
            })

        if self.status == self.Status.FAILED and not self.error_message:
            raise ValidationError({
                "error_message": "Failed restore should store an error message."
            })

    @property
    def mode_label(self):
        return self.get_restore_mode_display()

    @property
    def status_label(self):
        return self.get_status_display()

    @property
    def is_success(self):
        return self.status == self.Status.SUCCESS

    @property
    def is_failed(self):
        return self.status == self.Status.FAILED

    @property
    def is_running(self):
        return self.status == self.Status.RUNNING

    def mark_running(self):
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.completed_at = None
        self.error_message = ""
        self.save(update_fields=["status", "started_at", "completed_at", "error_message"])

    def mark_success(self, *, note: str = "", metadata: dict | None = None):
        self.status = self.Status.SUCCESS
        self.completed_at = timezone.now()
        self.note = (note or self.note or "").strip()
        if metadata is not None:
            self.metadata = metadata
        self.error_message = ""
        self.save()

    def mark_failed(self, error_message: str, *, note: str = ""):
        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.error_message = (error_message or "").strip()
        if note:
            self.note = (note or "").strip()
        self.save()

    def __str__(self):
        return f"{self.shop.code} - {self.get_restore_mode_display()} - {self.started_at:%Y-%m-%d %H:%M}"