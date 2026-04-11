import json
import hashlib
import tempfile
import zipfile
from decimal import Decimal
from datetime import date, datetime, time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlparse

from django.conf import settings
from django.db.models.fields.files import FileField
from django.utils import timezone

from pos.models import (
    Shop,
    Customer,
    Supplier,
    Category,
    Unit,
    Product,
    Purchase,
    PurchaseItem,
    Order,
    OrderItem,
    Expense,
    PaymentMethod,
    BankAccount,
    SalePayment,
    BankLedger,
    StockMovement,
    StockAdjustment,
    InventoryCount,
    InventoryCountItem,
    ProductReturn,
    ProductReturnItem,
    Banner,
    CustomUser,
)
from pos.models_backup import BackupSetting, BackupHistory


# =========================================================
# GENERIC HELPERS
# =========================================================
def ensure_backup_setting(shop: Shop) -> BackupSetting:
    obj, _ = BackupSetting.objects.get_or_create(
        shop=shop,
        defaults={
            "enabled": True,
            "frequency": BackupSetting.Frequency.DAILY,
            "backup_time": "23:30",
            "keep_last": 10,
            "include_media": True,
            "include_users": True,
            "include_settings": True,
            "default_restore_mode": BackupSetting.RestoreMode.FULL,
        },
    )
    return obj


def backup_root() -> Path:
    root = getattr(settings, "BACKUP_ROOT", None)
    if root:
        path = Path(root)
    else:
        path = Path(settings.MEDIA_ROOT) / "backups"

    path.mkdir(parents=True, exist_ok=True)
    return path


def shop_backup_dir(shop: Shop) -> Path:
    path = backup_root() / str(shop.code).strip().upper()
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_file_size(num_bytes: int) -> str:
    size = int(num_bytes or 0)
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


def safe_user_display(user) -> str:
    if not user:
        return ""
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
    return full_name or getattr(user, "username", "") or ""


def compute_sha256(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# =========================================================
# JSON / SERIALIZATION HELPERS
# =========================================================
def normalize_json_value(value):
    """
    Ubah value yang tidak langsung JSON serializable menjadi aman:
    - Decimal -> string
    - datetime/date/time -> isoformat
    - Path -> string
    Sisanya dikembalikan apa adanya.
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    return value


def deep_normalize_json(value):
    """
    Recursive sanitizer untuk payload dict/list besar sebelum json.dump
    agar aman dari Decimal atau object non-serializable lain.
    """
    if isinstance(value, dict):
        return {k: deep_normalize_json(v) for k, v in value.items()}

    if isinstance(value, list):
        return [deep_normalize_json(v) for v in value]

    if isinstance(value, tuple):
        return [deep_normalize_json(v) for v in value]

    return normalize_json_value(value)


def serialize_queryset(qs, fields):
    rows = []
    for obj in qs:
        item = {}
        for field in fields:
            value = getattr(obj, field, None)
            item[field] = normalize_json_value(value)
        rows.append(item)
    return rows


# =========================================================
# MEDIA EXPORT HELPERS
# =========================================================
def get_file_field_names(model_cls):
    """
    Cari semua FileField/ImageField secara dinamis.
    ImageField adalah subclass dari FileField, jadi cukup cek FileField.
    """
    names = []
    for field in model_cls._meta.get_fields():
        if isinstance(field, FileField):
            names.append(field.name)
    return names


def iter_media_source_querysets(shop: Shop, setting: BackupSetting):
    """
    Queryset object yang mungkin punya file/image field.
    Pendekatan ini aman karena:
    - hanya object milik tenant/shop terkait
    - model tanpa FileField akan otomatis dilewati
    """
    sources = [
        Shop.objects.filter(pk=shop.pk),
        Customer.objects.filter(shop=shop),
        Supplier.objects.filter(shop=shop),
        Category.objects.filter(shop=shop),
        Unit.objects.filter(shop=shop),
        Product.objects.filter(shop=shop),
        Purchase.objects.filter(shop=shop),
        PurchaseItem.objects.filter(purchase__shop=shop),
        Order.objects.filter(shop=shop),
        OrderItem.objects.filter(order__shop=shop),
        Expense.objects.filter(shop=shop),
        PaymentMethod.objects.filter(shop=shop),
        BankAccount.objects.filter(shop=shop),
        SalePayment.objects.filter(order__shop=shop),
        BankLedger.objects.filter(bank_account__shop=shop),
        StockMovement.objects.filter(shop=shop),
        StockAdjustment.objects.filter(shop=shop),
        InventoryCount.objects.filter(shop=shop),
        InventoryCountItem.objects.filter(inventory__shop=shop),
        ProductReturn.objects.filter(shop=shop),
        ProductReturnItem.objects.filter(product_return__shop=shop),
        Banner.objects.filter(shop=shop),
    ]

    if setting.include_users:
        sources.append(CustomUser.objects.filter(shop=shop))

    return sources


def _safe_remote_filename(file_name: str, fallback_name: str = "file.bin") -> str:
    name = (file_name or "").strip().replace("\\", "/").split("/")[-1]
    return name or fallback_name


def _download_remote_file_bytes(url: str, timeout: int = 20):
    req = Request(url, headers={"User-Agent": "ValdKerPOS-Backup/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        content = resp.read()
        content_type = resp.headers.get_content_type() if resp.headers else None
    return content, content_type


def collect_media_files(shop: Shop, setting: BackupSetting):
    """
    Kumpulkan file media yang terkait dengan shop.

    Mendukung 2 sumber:
    1. Local filesystem storage -> ambil dari file_attr.path
    2. Remote storage (mis. Cloudinary) -> ambil dari file_attr.url lalu download bytes

    Tidak melempar exception untuk file rusak/hilang; cukup skip dan catat.
    """
    collected = []
    skipped = []
    seen_zip_paths = set()
    seen_abs_paths = set()

    media_root = Path(settings.MEDIA_ROOT)

    for qs in iter_media_source_querysets(shop, setting):
        model_cls = qs.model
        file_fields = get_file_field_names(model_cls)
        if not file_fields:
            continue

        for obj in qs.iterator():
            model_label = obj._meta.model_name
            object_id = getattr(obj, "pk", None)

            for field_name in file_fields:
                try:
                    file_attr = getattr(obj, field_name, None)
                    if not file_attr:
                        continue

                    file_name = getattr(file_attr, "name", "") or ""
                    if not file_name:
                        continue

                    # -----------------------------------------
                    # 1) Coba file lokal via .path
                    # -----------------------------------------
                    abs_path = None
                    try:
                        abs_path = Path(file_attr.path)
                    except Exception:
                        abs_path = None

                    if abs_path and abs_path.exists() and abs_path.is_file():
                        abs_key = str(abs_path.resolve())
                        if abs_key in seen_abs_paths:
                            continue

                        try:
                            rel_to_media = abs_path.relative_to(media_root)
                            zip_path = f"media/{str(rel_to_media).replace('\\', '/')}"
                        except ValueError:
                            zip_path = (
                                f"media/_external/{model_label}/{object_id}/"
                                f"{field_name}_{abs_path.name}"
                            ).replace("\\", "/")

                        if zip_path in seen_zip_paths:
                            continue

                        seen_abs_paths.add(abs_key)
                        seen_zip_paths.add(zip_path)

                        collected.append({
                            "source_type": "local",
                            "abs_path": abs_path,
                            "zip_path": zip_path,
                            "model": model_label,
                            "object_id": object_id,
                            "field": field_name,
                            "file_name": file_name,
                            "size_bytes": abs_path.stat().st_size,
                        })
                        continue

                    # -----------------------------------------
                    # 2) Fallback remote via .url (Cloudinary, dst)
                    # -----------------------------------------
                    remote_url = ""
                    try:
                        remote_url = getattr(file_attr, "url", "") or ""
                    except Exception:
                        remote_url = ""

                    if remote_url:
                        parsed = urlparse(remote_url)
                        remote_name = _safe_remote_filename(
                            file_name or parsed.path.split("/")[-1],
                            "remote_file"
                        )

                        zip_path = (
                            f"media/remote/{model_label}/{object_id}/"
                            f"{field_name}_{remote_name}"
                        ).replace("\\", "/")

                        if zip_path in seen_zip_paths:
                            continue

                        try:
                            content, content_type = _download_remote_file_bytes(remote_url)
                            size_bytes = len(content)

                            seen_zip_paths.add(zip_path)

                            collected.append({
                                "source_type": "remote",
                                "content": content,
                                "content_type": content_type,
                                "remote_url": remote_url,
                                "zip_path": zip_path,
                                "model": model_label,
                                "object_id": object_id,
                                "field": field_name,
                                "file_name": remote_name,
                                "size_bytes": size_bytes,
                            })
                            continue
                        except Exception as e:
                            skipped.append({
                                "model": model_label,
                                "object_id": object_id,
                                "field": field_name,
                                "file_name": file_name,
                                "reason": f"remote download failed: {str(e)}",
                            })
                            continue

                    skipped.append({
                        "model": model_label,
                        "object_id": object_id,
                        "field": field_name,
                        "file_name": file_name,
                        "reason": "file path and remote url unavailable",
                    })

                except Exception as e:
                    skipped.append({
                        "model": model_label,
                        "object_id": object_id,
                        "field": field_name,
                        "file_name": "",
                        "reason": str(e),
                    })

    return {
        "files": collected,
        "skipped": skipped,
    }


def build_media_export_summary(media_result: dict) -> dict:
    files = media_result.get("files", []) or []
    skipped = media_result.get("skipped", []) or []

    total_bytes = sum(int(item.get("size_bytes") or 0) for item in files)

    return {
        "exported_count": len(files),
        "skipped_count": len(skipped),
        "total_size_bytes": total_bytes,
        "total_size_label": format_file_size(total_bytes),
        "exported_files": [
            {
                "zip_path": item["zip_path"],
                "model": item["model"],
                "object_id": item["object_id"],
                "field": item["field"],
                "file_name": item["file_name"],
                "size_bytes": item["size_bytes"],
                "source_type": item.get("source_type", "unknown"),
                "remote_url": item.get("remote_url", ""),
            }
            for item in files
        ],
        "skipped_files": skipped[:50],  # batasi agar metadata tidak terlalu besar
    }


# =========================================================
# PAYLOAD BUILDERS
# =========================================================
def build_backup_payload(shop: Shop, setting: BackupSetting) -> dict:
    """
    Shop-scoped export only.
    Aman untuk multi-tenant karena hanya export data milik shop terkait.
    """
    payload = {
        "metadata": {
            "shop_id": shop.id,
            "shop_code": shop.code,
            "shop_name": shop.name,
            "business_type": shop.business_type,
            "created_at": timezone.localtime().isoformat(),
            "included": {
                "database": True,
                "media": bool(setting.include_media),
                "users": bool(setting.include_users),
                "settings": bool(setting.include_settings),
            },
            "version": "1.0",
        },
        "data": {
            "shop": serialize_queryset(
                Shop.objects.filter(pk=shop.pk),
                [
                    "id",
                    "name",
                    "code",
                    "slug",
                    "business_type",
                    "address",
                    "phone",
                    "email",
                    "subdomain",
                    "custom_domain",
                    "frontend_url",
                    "backend_url",
                    "is_active",
                    "notes",
                    "created_at",
                    "updated_at",
                ],
            ),
            "customers": serialize_queryset(
                Customer.objects.filter(shop=shop).order_by("id"),
                ["id", "name", "cell", "email", "address", "points"],
            ),
            "suppliers": serialize_queryset(
                Supplier.objects.filter(shop=shop).order_by("id"),
                ["id", "name", "contact_person", "cell", "email", "address"],
            ),
            "categories": serialize_queryset(
                Category.objects.filter(shop=shop).order_by("id"),
                ["id", "name"],
            ),
            "units": serialize_queryset(
                Unit.objects.filter(shop=shop).order_by("id"),
                ["id", "name"],
            ),
            "products": serialize_queryset(
                Product.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "name",
                    "code",
                    "sku",
                    "item_type",
                    "category_id",
                    "description",
                    "stock",
                    "track_stock",
                    "buy_price",
                    "sell_price",
                    "weight",
                    "unit_id",
                    "supplier_id",
                    "is_active",
                    "created_at",
                    "updated_at",
                ],
            ),
            "purchases": serialize_queryset(
                Purchase.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "supplier_id",
                    "invoice_id",
                    "purchase_date",
                    "note",
                    "created_at",
                    "updated_at",
                    "created_by_id",
                ],
            ),
            "purchase_items": serialize_queryset(
                PurchaseItem.objects.filter(purchase__shop=shop).order_by("id"),
                [
                    "id",
                    "purchase_id",
                    "product_id",
                    "quantity",
                    "cost_price",
                    "expired_date",
                    "batch_code",
                    "created_at",
                ],
            ),
            "orders": serialize_queryset(
                Order.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "invoice_number",
                    "customer_id",
                    "created_at",
                    "payment_method",
                    "subtotal",
                    "discount",
                    "tax",
                    "total",
                    "notes",
                    "is_paid",
                    "default_order_type",
                    "table_number",
                    "delivery_address",
                    "delivery_fee",
                    "served_by_id",
                ],
            ),
            "order_items": serialize_queryset(
                OrderItem.objects.filter(order__shop=shop).order_by("id"),
                ["id", "order_id", "product_id", "quantity", "price", "weight_unit_id", "order_type"],
            ),
            "expenses": serialize_queryset(
                Expense.objects.filter(shop=shop).order_by("id"),
                ["id", "name", "note", "amount", "date", "time"],
            ),
            "payment_methods": serialize_queryset(
                PaymentMethod.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "name",
                    "code",
                    "payment_type",
                    "requires_bank_account",
                    "is_active",
                    "note",
                ],
            ),
            "bank_accounts": serialize_queryset(
                BankAccount.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "name",
                    "bank_name",
                    "account_number",
                    "account_holder",
                    "account_type",
                    "opening_balance",
                    "current_balance",
                    "is_active",
                    "note",
                    "created_at",
                ],
            ),
            "sale_payments": serialize_queryset(
                SalePayment.objects.filter(order__shop=shop).order_by("id"),
                [
                    "id",
                    "order_id",
                    "payment_method_id",
                    "bank_account_id",
                    "amount",
                    "reference_number",
                    "note",
                    "paid_at",
                    "created_by_id",
                ],
            ),
            "bank_ledgers": serialize_queryset(
                BankLedger.objects.filter(bank_account__shop=shop).order_by("id"),
                [
                    "id",
                    "bank_account_id",
                    "transaction_type",
                    "direction",
                    "amount",
                    "balance_before",
                    "balance_after",
                    "reference_order_id",
                    "reference_payment_id",
                    "description",
                    "created_at",
                    "created_by_id",
                ],
            ),
            "stock_movements": serialize_queryset(
                StockMovement.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "product_id",
                    "movement_type",
                    "quantity_delta",
                    "before_stock",
                    "after_stock",
                    "note",
                    "ref_model",
                    "ref_id",
                    "created_at",
                    "created_by_id",
                ],
            ),
            "stock_adjustments": serialize_queryset(
                StockAdjustment.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "product_id",
                    "old_stock",
                    "new_stock",
                    "reason",
                    "note",
                    "adjusted_at",
                    "adjusted_by_id",
                ],
            ),
            "inventory_counts": serialize_queryset(
                InventoryCount.objects.filter(shop=shop).order_by("id"),
                [
                    "id",
                    "title",
                    "note",
                    "counted_at",
                    "counted_by_id",
                    "status",
                    "created_at",
                ],
            ),
            "inventory_count_items": serialize_queryset(
                InventoryCountItem.objects.filter(inventory__shop=shop).order_by("id"),
                ["id", "inventory_id", "product_id", "system_stock", "counted_stock"],
            ),
            "product_returns": serialize_queryset(
                ProductReturn.objects.filter(shop=shop).order_by("id"),
                ["id", "order_id", "customer_id", "note", "returned_at", "returned_by_id"],
            ),
            "product_return_items": serialize_queryset(
                ProductReturnItem.objects.filter(product_return__shop=shop).order_by("id"),
                ["id", "product_return_id", "product_id", "quantity", "unit_price"],
            ),
            "banners": serialize_queryset(
                Banner.objects.filter(shop=shop).order_by("id"),
                ["id", "title", "active"],
            ),
        },
    }

    if setting.include_users:
        payload["data"]["users"] = serialize_queryset(
            CustomUser.objects.filter(shop=shop).order_by("id"),
            [
                "id",
                "username",
                "first_name",
                "last_name",
                "email",
                "role",
                "is_active",
                "date_joined",
                "last_login",
            ],
        )

    if setting.include_settings:
        payload["data"]["backup_setting"] = {
            "enabled": setting.enabled,
            "frequency": setting.frequency,
            "backup_time": setting.backup_time.isoformat() if setting.backup_time else None,
            "keep_last": setting.keep_last,
            "include_media": setting.include_media,
            "include_users": setting.include_users,
            "include_settings": setting.include_settings,
            "default_restore_mode": setting.default_restore_mode,
            "last_auto_backup_at": setting.last_auto_backup_at.isoformat() if setting.last_auto_backup_at else None,
            "last_manual_backup_at": setting.last_manual_backup_at.isoformat() if setting.last_manual_backup_at else None,
        }

    return deep_normalize_json(payload)


# =========================================================
# ZIP CREATION
# =========================================================
def create_backup_zip(
    *,
    shop: Shop,
    setting: BackupSetting,
    backup_history: BackupHistory,
) -> dict:
    """
    Membuat backup zip berisi:
    - metadata.json
    - data.json
    - media/... (jika include_media=True dan file ada)

    Mendukung:
    - local media file -> zip dari abs_path
    - remote media file -> download bytes lalu tulis ke zip
    """
    backup_dir = shop_backup_dir(shop)

    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{shop.code}_backup_{timestamp}.zip"
    zip_path = backup_dir / zip_name

    payload = build_backup_payload(shop, setting)

    media_result = {"files": [], "skipped": []}
    if setting.include_media:
        media_result = collect_media_files(shop, setting)
        payload["metadata"]["media_export"] = build_media_export_summary(media_result)
    else:
        payload["metadata"]["media_export"] = {
            "exported_count": 0,
            "skipped_count": 0,
            "total_size_bytes": 0,
            "total_size_label": "0 B",
            "exported_files": [],
            "skipped_files": [],
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        metadata_path = tmpdir_path / "metadata.json"
        data_path = tmpdir_path / "data.json"

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(payload["metadata"], f, ensure_ascii=False, indent=2)

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(payload["data"], f, ensure_ascii=False, indent=2)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(metadata_path, arcname="metadata.json")
            zf.write(data_path, arcname="data.json")

            # export media fisik / remote
            for item in media_result.get("files", []):
                try:
                    if item.get("source_type") == "local" and item.get("abs_path"):
                        zf.write(item["abs_path"], arcname=item["zip_path"])
                    elif item.get("source_type") == "remote":
                        zf.writestr(item["zip_path"], item["content"])
                except Exception:
                    # jangan bikin seluruh backup gagal hanya karena 1 file bermasalah
                    pass

    file_size_bytes = zip_path.stat().st_size
    checksum = compute_sha256(zip_path)

    media_root_path = Path(settings.MEDIA_ROOT)
    try:
        rel_media_path = zip_path.relative_to(media_root_path)
        backup_history.file.name = str(rel_media_path).replace("\\", "/")
    except ValueError:
        # fallback kalau BACKUP_ROOT berada di luar MEDIA_ROOT
        backup_history.file.name = f"backups/{shop.code.strip().upper()}/{zip_name}"

    return {
        "file_name": zip_name,
        "file_path": str(zip_path),
        "file_size_bytes": file_size_bytes,
        "file_size_label": format_file_size(file_size_bytes),
        "checksum": checksum,
        "metadata": payload["metadata"],
    }


# =========================================================
# CLEANUP
# =========================================================
def cleanup_old_backups(shop: Shop, keep_last: int):
    qs = BackupHistory.objects.filter(
        shop=shop,
        deleted_at__isnull=True,
        status=BackupHistory.Status.SUCCESS,
    ).order_by("-completed_at", "-id")

    keep_count = max(int(keep_last or 0), 0)
    old_items = list(qs[keep_count:])

    for item in old_items:
        if item.file:
            try:
                storage = item.file.storage
                if storage.exists(item.file.name):
                    storage.delete(item.file.name)
            except Exception:
                pass
        item.soft_delete()


# =========================================================
# HIGH LEVEL ACTION
# =========================================================
def run_manual_backup(
    *,
    shop: Shop,
    user=None,
    include_media=None,
    include_users=None,
    include_settings=None,
) -> BackupHistory:
    setting = ensure_backup_setting(shop)

    final_include_media = setting.include_media if include_media is None else bool(include_media)
    final_include_users = setting.include_users if include_users is None else bool(include_users)
    final_include_settings = setting.include_settings if include_settings is None else bool(include_settings)

    backup = BackupHistory.objects.create(
        shop=shop,
        backup_type=BackupHistory.BackupType.MANUAL,
        status=BackupHistory.Status.RUNNING,
        triggered_by=safe_user_display(user),
        created_by=user if getattr(user, "is_superuser", False) is False else None,
        include_database=True,
        include_media=final_include_media,
        include_users=final_include_users,
        include_settings=final_include_settings,
        started_at=timezone.now(),
        metadata={},
    )

    try:
        # clone simple setting state for payload purpose
        temp_setting = setting
        temp_setting.include_media = final_include_media
        temp_setting.include_users = final_include_users
        temp_setting.include_settings = final_include_settings

        result = create_backup_zip(
            shop=shop,
            setting=temp_setting,
            backup_history=backup,
        )

        backup.mark_success(
            file_name=result["file_name"],
            file_size_bytes=result["file_size_bytes"],
            file_size_label=result["file_size_label"],
            checksum=result["checksum"],
            metadata=result["metadata"],
        )

        setting.last_manual_backup_at = backup.completed_at
        setting.save(update_fields=["last_manual_backup_at", "updated_at"])

        cleanup_old_backups(shop, setting.keep_last)
        return backup

    except Exception as e:
        backup.mark_failed(str(e))
        raise