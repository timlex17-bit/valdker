# pos/services/restore_service.py

import json
import os
import tempfile
import zipfile
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from pos.models import Shop
from pos.models_backup import BackupHistory, RestoreHistory


# =========================================================
# HELPERS
# =========================================================
def safe_user_display(user) -> str:
    if not user:
        return ""
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
    return full_name or getattr(user, "username", "") or ""


def validate_backup_history_for_restore(backup: BackupHistory):
    if not backup:
        raise ValueError("Backup object is required.")

    if backup.status != BackupHistory.Status.SUCCESS:
        raise ValueError("Only successful backups can be restored.")

    if backup.deleted_at is not None:
        raise ValueError("Deleted backup cannot be restored.")

    if not backup.file:
        raise ValueError("Backup file is missing.")

    backup_path = Path(backup.file.path)
    if not backup_path.exists():
        raise ValueError("Backup file does not exist on disk.")

    if backup_path.suffix.lower() != ".zip":
        raise ValueError("Backup file must be a ZIP package.")

    return backup_path


def extract_backup_package(backup: BackupHistory) -> tuple[Path, tempfile.TemporaryDirectory]:
    """
    Return:
    - extract dir path
    - TemporaryDirectory object (must be kept alive by caller)
    """
    backup_path = validate_backup_history_for_restore(backup)

    tmpdir = tempfile.TemporaryDirectory()
    extract_dir = Path(tmpdir.name)

    with zipfile.ZipFile(backup_path, "r") as zf:
        zf.extractall(extract_dir)

    return extract_dir, tmpdir


def load_backup_package(backup: BackupHistory) -> dict:
    """
    Safe loader helper.
    """
    extract_dir, tmpdir = extract_backup_package(backup)
    try:
        metadata_path = extract_dir / "metadata.json"
        data_path = extract_dir / "data.json"

        if not metadata_path.exists():
            raise ValueError("metadata.json not found in backup package.")

        if not data_path.exists():
            raise ValueError("data.json not found in backup package.")

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(metadata, dict):
            raise ValueError("metadata.json format is invalid.")

        if not isinstance(data, dict):
            raise ValueError("data.json format is invalid.")

        return {
            "metadata": metadata,
            "data": data,
        }
    finally:
        tmpdir.cleanup()


def validate_restore_payload(*, shop: Shop, backup: BackupHistory, package: dict):
    metadata = package.get("metadata") or {}
    data = package.get("data") or {}

    if not isinstance(metadata, dict):
        raise ValueError("Backup metadata is invalid.")

    if not isinstance(data, dict):
        raise ValueError("Backup data is invalid.")

    backup_shop_id = metadata.get("shop_id")
    backup_shop_code = metadata.get("shop_code")

    if backup_shop_id and int(backup_shop_id) != int(shop.id):
        raise ValueError("Backup shop_id does not match current shop.")

    if backup_shop_code and str(backup_shop_code).strip().upper() != str(shop.code).strip().upper():
        raise ValueError("Backup shop_code does not match current shop.")

    if "shop" not in data:
        raise ValueError("Backup data missing shop section.")

    return True


# =========================================================
# RESTORE ENGINE - SAFE PHASE
# =========================================================
def create_restore_history(*, shop: Shop, backup: BackupHistory, mode: str, user=None) -> RestoreHistory:
    return RestoreHistory.objects.create(
        shop=shop,
        backup=backup,
        restore_mode=mode,
        status=RestoreHistory.Status.RUNNING,
        restored_by=user if getattr(user, "is_superuser", False) is False else None,
        triggered_by=safe_user_display(user),
        started_at=timezone.now(),
        metadata={},
    )


@transaction.atomic
def run_restore_validation(*, shop: Shop, backup: BackupHistory, mode: str, user=None) -> RestoreHistory:
    """
    Tahap aman:
    - validasi backup history
    - extract zip
    - load metadata.json + data.json
    - validasi shop cocok
    - simpan hasil validasi ke RestoreHistory

    Belum melakukan overwrite/import database.
    """
    restore = create_restore_history(
        shop=shop,
        backup=backup,
        mode=mode,
        user=user,
    )

    try:
        package = load_backup_package(backup)
        validate_restore_payload(shop=shop, backup=backup, package=package)

        available_keys = sorted(list((package.get("data") or {}).keys()))

        restore.mark_success(
            note=f"Restore validation completed with mode: {mode}. Actual import engine not implemented yet.",
            metadata={
                "validated": True,
                "mode": mode,
                "shop_id": shop.id,
                "shop_code": shop.code,
                "backup_id": backup.id,
                "available_keys": available_keys,
                "metadata": package.get("metadata", {}),
            },
        )
        return restore

    except Exception as e:
        restore.mark_failed(str(e))
        raise


# =========================================================
# FUTURE RESTORE STUBS
# =========================================================
def restore_master_data(*, shop: Shop, package: dict, user=None):
    """
    Tahap berikutnya:
    restore hanya master data seperti:
    - categories
    - units
    - suppliers
    - customers
    - products
    - payment methods
    - bank accounts
    - settings dasar
    """
    raise NotImplementedError("restore_master_data is not implemented yet.")


def restore_full_data(*, shop: Shop, package: dict, user=None):
    """
    Tahap berikutnya:
    restore full data termasuk transaksi.
    Harus dibuat sangat hati-hati agar tidak merusak tenant data existing.
    """
    raise NotImplementedError("restore_full_data is not implemented yet.")