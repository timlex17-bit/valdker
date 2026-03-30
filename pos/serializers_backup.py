# pos/serializers_backup.py

from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import serializers

from .models_backup import BackupSetting, BackupHistory, RestoreHistory


# ==========================================================
# HELPERS
# ==========================================================
def _human_file_size(num_bytes: int) -> str:
    """
    Convert bytes to a readable label like:
    0 B, 12.4 KB, 5.2 MB, 1.1 GB
    """
    try:
        size = int(num_bytes or 0)
    except Exception:
        size = 0

    if size < 1024:
        return f"{size} B"

    kb = size / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"

    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"

    gb = mb / 1024
    return f"{gb:.1f} GB"


def _safe_user_display(user) -> str:
    if not user:
        return ""
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
    return full_name or getattr(user, "username", "") or ""


def _compute_next_scheduled_backup(setting: BackupSetting):
    """
    Perhitungan sederhana untuk UI summary.
    Ini bukan scheduler final, hanya preview waktu backup berikutnya.
    """
    if not setting.enabled:
        return None

    now = timezone.localtime()
    backup_time = setting.backup_time

    candidate = now.replace(
        hour=backup_time.hour,
        minute=backup_time.minute,
        second=0,
        microsecond=0,
    )

    if setting.frequency == BackupSetting.Frequency.DAILY:
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if setting.frequency == BackupSetting.Frequency.WEEKLY:
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    if setting.frequency == BackupSetting.Frequency.MONTHLY:
        # preview sederhana: +30 hari
        if candidate <= now:
            candidate += timedelta(days=30)
        return candidate

    return candidate


# ==========================================================
# BASE / SMALL SERIALIZERS
# ==========================================================
class BackupUserMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField()


class BackupShopMiniSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()


# ==========================================================
# BACKUP SETTING
# ==========================================================
class BackupSettingSerializer(serializers.ModelSerializer):
    shop = serializers.SerializerMethodField()
    frequency_label = serializers.CharField(source="get_frequency_display", read_only=True)
    default_restore_mode_label = serializers.CharField(
        source="get_default_restore_mode_display",
        read_only=True
    )
    auto_backup_status = serializers.CharField(source="auto_backup_status_label", read_only=True)
    backup_time_display = serializers.SerializerMethodField()

    class Meta:
        model = BackupSetting
        fields = [
            "id",
            "shop",
            "enabled",
            "auto_backup_status",
            "frequency",
            "frequency_label",
            "backup_time",
            "backup_time_display",
            "keep_last",
            "include_media",
            "include_users",
            "include_settings",
            "default_restore_mode",
            "default_restore_mode_label",
            "last_auto_backup_at",
            "last_manual_backup_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "shop",
            "auto_backup_status",
            "frequency_label",
            "default_restore_mode_label",
            "backup_time_display",
            "last_auto_backup_at",
            "last_manual_backup_at",
            "updated_at",
        ]

    def get_shop(self, obj):
        if not obj.shop_id:
            return None
        return {
            "id": obj.shop_id,
            "name": obj.shop.name,
            "code": obj.shop.code,
        }

    def get_backup_time_display(self, obj):
        if not obj.backup_time:
            return ""
        return obj.backup_time.strftime("%H:%M")

    def validate_keep_last(self, value):
        if value < 1:
            raise serializers.ValidationError("Keep last backup must be at least 1.")
        if value > 365:
            raise serializers.ValidationError("Keep last backup is too large.")
        return value

    def validate(self, attrs):
        instance = getattr(self, "instance", None)

        enabled = attrs.get("enabled", getattr(instance, "enabled", True))
        frequency = attrs.get("frequency", getattr(instance, "frequency", BackupSetting.Frequency.DAILY))
        backup_time = attrs.get("backup_time", getattr(instance, "backup_time", None))
        default_restore_mode = attrs.get(
            "default_restore_mode",
            getattr(instance, "default_restore_mode", BackupSetting.RestoreMode.FULL)
        )

        if enabled and not backup_time:
            raise serializers.ValidationError({
                "backup_time": "Backup time is required when automatic backup is enabled."
            })

        valid_frequencies = {
            BackupSetting.Frequency.DAILY,
            BackupSetting.Frequency.WEEKLY,
            BackupSetting.Frequency.MONTHLY,
        }
        if frequency not in valid_frequencies:
            raise serializers.ValidationError({"frequency": "Invalid frequency."})

        valid_modes = {
            BackupSetting.RestoreMode.FULL,
            BackupSetting.RestoreMode.MASTER,
        }
        if default_restore_mode not in valid_modes:
            raise serializers.ValidationError({"default_restore_mode": "Invalid restore mode."})

        return attrs


# ==========================================================
# BACKUP HISTORY LIST
# ==========================================================
class BackupHistoryListSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="type_label", read_only=True)
    status = serializers.CharField(source="status_label", read_only=True)
    triggered_by = serializers.SerializerMethodField()
    date_time = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    included = serializers.ListField(source="included_items", read_only=True)
    shop = serializers.SerializerMethodField()
    created_by_user = serializers.SerializerMethodField()
    can_restore = serializers.SerializerMethodField()
    can_download = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = BackupHistory
        fields = [
            "id",
            "shop",
            "date_time",
            "started_at",
            "completed_at",
            "type",
            "backup_type",
            "triggered_by",
            "created_by_user",
            "status",
            "file_size",
            "file_size_bytes",
            "included",
            "note",
            "can_restore",
            "can_download",
            "can_delete",
        ]

    def get_shop(self, obj):
        return {
            "id": obj.shop_id,
            "name": obj.shop.name,
            "code": obj.shop.code,
        }

    def get_triggered_by(self, obj):
        if obj.triggered_by:
            return obj.triggered_by
        if obj.created_by:
            return _safe_user_display(obj.created_by)
        return "System Scheduler" if obj.backup_type == BackupHistory.BackupType.AUTO else ""

    def get_created_by_user(self, obj):
        if not obj.created_by:
            return None
        return {
            "id": obj.created_by.id,
            "username": obj.created_by.username,
            "display_name": _safe_user_display(obj.created_by),
        }

    def get_date_time(self, obj):
        dt = obj.completed_at or obj.started_at
        if not dt:
            return ""
        local_dt = timezone.localtime(dt)
        return local_dt.strftime("%Y-%m-%d %H:%M")

    def get_file_size(self, obj):
        if obj.status == BackupHistory.Status.RUNNING:
            return "Preparing..."
        if obj.file_size_label:
            return obj.file_size_label
        return _human_file_size(obj.file_size_bytes)

    def get_can_restore(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if obj.status != BackupHistory.Status.SUCCESS:
            return False

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        role = (getattr(user, "role", "") or "").lower().strip()
        return role == "owner"

    def get_can_download(self, obj):
        return obj.status == BackupHistory.Status.SUCCESS and bool(obj.file)

    def get_can_delete(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "is_superuser", False):
            return True

        role = (getattr(user, "role", "") or "").lower().strip()
        return role == "owner"


# ==========================================================
# BACKUP HISTORY DETAIL
# ==========================================================
class BackupHistoryDetailSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="type_label", read_only=True)
    status = serializers.CharField(source="status_label", read_only=True)
    triggered_by = serializers.SerializerMethodField()
    date_time = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    included = serializers.ListField(source="included_items", read_only=True)
    shop = serializers.SerializerMethodField()
    created_by_user = serializers.SerializerMethodField()

    file_url = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    restore_count = serializers.SerializerMethodField()

    class Meta:
        model = BackupHistory
        fields = [
            "id",
            "shop",
            "date_time",
            "started_at",
            "completed_at",
            "duration_seconds",
            "type",
            "backup_type",
            "status",
            "triggered_by",
            "created_by_user",
            "file_name",
            "file_url",
            "file_size",
            "file_size_bytes",
            "file_checksum",
            "included",
            "include_database",
            "include_media",
            "include_users",
            "include_settings",
            "note",
            "error_message",
            "metadata",
            "restore_count",
            "deleted_at",
        ]

    def get_shop(self, obj):
        return {
            "id": obj.shop_id,
            "name": obj.shop.name,
            "code": obj.shop.code,
        }

    def get_triggered_by(self, obj):
        if obj.triggered_by:
            return obj.triggered_by
        if obj.created_by:
            return _safe_user_display(obj.created_by)
        return "System Scheduler" if obj.backup_type == BackupHistory.BackupType.AUTO else ""

    def get_created_by_user(self, obj):
        if not obj.created_by:
            return None
        return {
            "id": obj.created_by.id,
            "username": obj.created_by.username,
            "display_name": _safe_user_display(obj.created_by),
        }

    def get_date_time(self, obj):
        dt = obj.completed_at or obj.started_at
        if not dt:
            return ""
        local_dt = timezone.localtime(dt)
        return local_dt.strftime("%Y-%m-%d %H:%M")

    def get_file_size(self, obj):
        if obj.status == BackupHistory.Status.RUNNING:
            return "Preparing..."
        if obj.file_size_label:
            return obj.file_size_label
        return _human_file_size(obj.file_size_bytes)

    def get_file_url(self, obj):
        request = self.context.get("request")
        if not obj.file:
            return None
        try:
            url = obj.file.url
        except Exception:
            return None
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_duration_seconds(self, obj):
        if not obj.started_at or not obj.completed_at:
            return None
        delta = obj.completed_at - obj.started_at
        return max(0, int(delta.total_seconds()))

    def get_restore_count(self, obj):
        return obj.restore_histories.count()


# ==========================================================
# RESTORE HISTORY
# ==========================================================
class RestoreHistorySerializer(serializers.ModelSerializer):
    mode = serializers.CharField(source="mode_label", read_only=True)
    status = serializers.CharField(source="status_label", read_only=True)
    date_time = serializers.SerializerMethodField()
    shop = serializers.SerializerMethodField()
    restored_by_user = serializers.SerializerMethodField()
    backup_info = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = RestoreHistory
        fields = [
            "id",
            "shop",
            "backup",
            "backup_info",
            "restore_mode",
            "mode",
            "status",
            "triggered_by",
            "restored_by_user",
            "started_at",
            "completed_at",
            "date_time",
            "duration_seconds",
            "note",
            "error_message",
            "metadata",
        ]

    def get_shop(self, obj):
        return {
            "id": obj.shop_id,
            "name": obj.shop.name,
            "code": obj.shop.code,
        }

    def get_backup_info(self, obj):
        if not obj.backup_id:
            return None
        return {
            "id": obj.backup.id,
            "file_name": obj.backup.file_name,
            "status": obj.backup.get_status_display(),
            "date_time": timezone.localtime(obj.backup.completed_at or obj.backup.started_at).strftime("%Y-%m-%d %H:%M")
            if (obj.backup.completed_at or obj.backup.started_at) else "",
        }

    def get_restored_by_user(self, obj):
        if not obj.restored_by:
            return None
        return {
            "id": obj.restored_by.id,
            "username": obj.restored_by.username,
            "display_name": _safe_user_display(obj.restored_by),
        }

    def get_date_time(self, obj):
        dt = obj.completed_at or obj.started_at
        if not dt:
            return ""
        return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")

    def get_duration_seconds(self, obj):
        if not obj.started_at or not obj.completed_at:
            return None
        delta = obj.completed_at - obj.started_at
        return max(0, int(delta.total_seconds()))


# ==========================================================
# RESTORE REQUEST
# ==========================================================
class RestoreRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=[
            (BackupSetting.RestoreMode.FULL, "Full Restore"),
            (BackupSetting.RestoreMode.MASTER, "Master Data Only"),
        ],
        default=BackupSetting.RestoreMode.FULL
    )

    confirm_overwrite = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("confirm_overwrite"):
            raise serializers.ValidationError({
                "confirm_overwrite": "You must confirm overwrite before restore."
            })
        return attrs


# ==========================================================
# BACKUP RUN REQUEST
# ==========================================================
class BackupRunRequestSerializer(serializers.Serializer):
    """
    Opsional.
    Kalau nanti tombol 'Run backup now' ingin override include options
    tanpa mengubah setting default shop, serializer ini bisa dipakai.
    """
    include_media = serializers.BooleanField(required=False)
    include_users = serializers.BooleanField(required=False)
    include_settings = serializers.BooleanField(required=False)

    def validate(self, attrs):
        return attrs


# ==========================================================
# BACKUP SUMMARY
# ==========================================================
class BackupSummarySerializer(serializers.Serializer):
    auto_backup_status = serializers.CharField()
    next_scheduled_backup = serializers.CharField(allow_blank=True, allow_null=True)
    frequency = serializers.CharField()
    time = serializers.CharField()
    last_successful_backup = serializers.CharField(allow_blank=True, allow_null=True)
    retention_keep_last = serializers.IntegerField()

    enabled = serializers.BooleanField()
    frequency_value = serializers.CharField()
    default_restore_mode = serializers.CharField()
    last_successful_backup_id = serializers.IntegerField(allow_null=True)

    @classmethod
    def build(cls, setting: BackupSetting):
        next_dt = _compute_next_scheduled_backup(setting)

        latest_success = (
            BackupHistory.objects
            .filter(
                shop=setting.shop,
                status=BackupHistory.Status.SUCCESS,
                deleted_at__isnull=True,
            )
            .order_by("-completed_at", "-id")
            .first()
        )

        return {
            "auto_backup_status": "Enabled" if setting.enabled else "Disabled",
            "next_scheduled_backup": (
                timezone.localtime(next_dt).strftime("%Y-%m-%d %H:%M") if next_dt else "Disabled"
            ),
            "frequency": setting.get_frequency_display(),
            "time": setting.backup_time.strftime("%H:%M") if setting.backup_time else "",
            "last_successful_backup": (
                timezone.localtime(latest_success.completed_at or latest_success.started_at).strftime("%Y-%m-%d %H:%M")
                if latest_success else "No successful backup yet"
            ),
            "retention_keep_last": setting.keep_last,

            "enabled": setting.enabled,
            "frequency_value": setting.frequency,
            "default_restore_mode": setting.default_restore_mode,
            "last_successful_backup_id": latest_success.id if latest_success else None,
        }


# ==========================================================
# OPTIONAL: COMBINED RESPONSE SERIALIZER
# ==========================================================
class BackupCenterBootstrapSerializer(serializers.Serializer):
    """
    Opsional untuk endpoint bootstrap kalau nanti Anda ingin
    sekali hit semua data awal halaman:
    - summary
    - settings
    - history
    """
    summary = BackupSummarySerializer()
    settings = BackupSettingSerializer()
    history = BackupHistoryListSerializer(many=True)