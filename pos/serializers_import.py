# pos/serializers_import.py

from rest_framework import serializers

from .models_import import ImportJob, ImportRowError


def _human_file_size(num_bytes: int) -> str:
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


class ImportRowErrorSerializer(serializers.ModelSerializer):
    row = serializers.IntegerField(source="row_number", read_only=True)
    sheet = serializers.CharField(source="sheet_name", read_only=True)
    field = serializers.CharField(source="field_name", read_only=True)

    class Meta:
        model = ImportRowError
        fields = [
            "id",
            "row",
            "sheet",
            "field",
            "message",
        ]


class ImportJobListSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="status_label", read_only=True)
    file_size = serializers.SerializerMethodField()
    uploaded_by_user = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "original_filename",
            "status",
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "imported_rows",
            "skipped_rows",
            "file_size",
            "uploaded_by_user",
            "created_at",
            "validated_at",
            "completed_at",
            "note",
        ]

    def get_file_size(self, obj):
        return _human_file_size(obj.file_size_bytes)

    def get_uploaded_by_user(self, obj):
        if not obj.uploaded_by:
            return None
        return {
            "id": obj.uploaded_by.id,
            "username": obj.uploaded_by.username,
            "display_name": _safe_user_display(obj.uploaded_by),
        }


class ImportJobDetailSerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="status_label", read_only=True)
    file_size = serializers.SerializerMethodField()
    uploaded_by_user = serializers.SerializerMethodField()
    validation_errors = ImportRowErrorSerializer(source="row_errors", many=True, read_only=True)
    shop = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "shop",
            "original_filename",
            "status",
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "imported_rows",
            "skipped_rows",
            "file_size",
            "uploaded_by_user",
            "created_at",
            "validated_at",
            "completed_at",
            "note",
            "error_message",
            "metadata",
            "validation_errors",
        ]

    def get_file_size(self, obj):
        return _human_file_size(obj.file_size_bytes)

    def get_uploaded_by_user(self, obj):
        if not obj.uploaded_by:
            return None
        return {
            "id": obj.uploaded_by.id,
            "username": obj.uploaded_by.username,
            "display_name": _safe_user_display(obj.uploaded_by),
        }

    def get_shop(self, obj):
        return {
            "id": obj.shop_id,
            "name": obj.shop.name,
            "code": obj.shop.code,
        }


class ImportUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        name = (getattr(value, "name", "") or "").lower()
        if not name.endswith(".xlsx"):
            raise serializers.ValidationError("Only .xlsx files are allowed.")
        return value


class ImportValidateResponseSerializer(serializers.Serializer):
    import_job_id = serializers.IntegerField()
    total_rows = serializers.IntegerField()
    valid_rows = serializers.IntegerField()
    invalid_rows = serializers.IntegerField()
    errors = ImportRowErrorSerializer(many=True)


class ImportConfirmSerializer(serializers.Serializer):
    confirm_import = serializers.BooleanField(default=False)
    skip_backup_check = serializers.BooleanField(default=False)

    def validate(self, attrs):
        if not attrs.get("confirm_import"):
            raise serializers.ValidationError({
                "confirm_import": "You must confirm import before processing."
            })
        return attrs


class ImportTemplateInfoSerializer(serializers.Serializer):
    filename = serializers.CharField()
    format = serializers.CharField()
    sheets = serializers.ListField(child=serializers.CharField())
    description = serializers.CharField()


class ImportSummarySerializer(serializers.Serializer):
    total_rows = serializers.IntegerField()
    valid_rows = serializers.IntegerField()
    invalid_rows = serializers.IntegerField()