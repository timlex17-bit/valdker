# pos/services/import_service.py

from io import BytesIO

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from pos.models import (
    Category,
    Unit,
    Product,
    Customer,
    Supplier,
    StockMovement,
)
from pos.models_backup import BackupHistory
from pos.models_import import ImportJob, ImportRowError


# =========================================================
# TEMPLATE
# =========================================================
TEMPLATE_SHEETS = {
    "Categories": ["name"],
    "Units": ["name"],
    "Products": [
        "name",
        "code",
        "sku",
        "item_type",
        "category",
        "unit",
        "supplier",
        "buy_price",
        "sell_price",
        "stock",
        "track_stock",
        "description",
        "is_active",
    ],
    "Customers": ["name", "cell", "email", "address", "points"],
    "Suppliers": ["name", "contact_person", "cell", "email", "address"],
    "OpeningStock": ["product_code", "quantity"],
}


def build_template_workbook():
    wb = Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)

    for sheet_name, headers in TEMPLATE_SHEETS.items():
        ws = wb.create_sheet(title=sheet_name)
        ws.append(headers)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def template_info():
    return {
        "filename": "ValdKerPOS_Master_Import_Template.xlsx",
        "format": "Excel Workbook",
        "sheets": list(TEMPLATE_SHEETS.keys()),
        "description": "One file with multiple sheets for importing master data.",
    }


# =========================================================
# FILE HELPERS
# =========================================================
def _safe_str(value):
    return (str(value).strip() if value is not None else "")


def _safe_int(value, default=0):
    if value in ("", None):
        return default
    try:
        return int(float(value))
    except Exception:
        raise ValueError("Must be a numeric value.")


def _safe_decimal(value, default=0):
    if value in ("", None):
        return default
    try:
        return float(value)
    except Exception:
        raise ValueError("Must be a numeric value.")


def _safe_bool(value, default=False):
    if value in (True, False):
        return value
    if value is None or value == "":
        return default

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _sheet_headers(ws):
    return [_safe_str(c.value) for c in ws[1]] if ws.max_row >= 1 else []


def _row_to_dict(headers, row):
    data = {}
    for idx, header in enumerate(headers):
        data[header] = row[idx] if idx < len(row) else None
    return data


def _clear_previous_errors(import_job: ImportJob):
    import_job.row_errors.all().delete()


def _add_error(import_job: ImportJob, sheet_name: str, row_number: int, field_name: str, message: str):
    ImportRowError.objects.create(
        import_job=import_job,
        sheet_name=sheet_name,
        row_number=row_number,
        field_name=field_name,
        message=message,
    )


# =========================================================
# VALIDATION
# =========================================================
def validate_import_workbook(import_job: ImportJob):
    if not import_job.file:
        raise ValueError("Import file is missing.")

    _clear_previous_errors(import_job)

    wb = load_workbook(import_job.file.path, data_only=True)

    for required_sheet, required_headers in TEMPLATE_SHEETS.items():
        if required_sheet not in wb.sheetnames:
            _add_error(import_job, required_sheet, 1, "", f"Sheet '{required_sheet}' is missing.")
            continue

        ws = wb[required_sheet]
        actual_headers = _sheet_headers(ws)

        if actual_headers != required_headers:
            _add_error(
                import_job,
                required_sheet,
                1,
                "",
                f"Invalid headers. Expected: {required_headers}",
            )

    total_rows = 0
    valid_rows = 0
    invalid_rows = 0

    for sheet_name, headers in TEMPLATE_SHEETS.items():
        if sheet_name not in wb.sheetnames:
            continue

        ws = wb[sheet_name]
        actual_headers = _sheet_headers(ws)
        if actual_headers != headers:
            continue

        for excel_row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            row_values = list(row or [])
            if not any(v not in ("", None) for v in row_values):
                continue

            total_rows += 1
            row_has_error = False
            row_data = _row_to_dict(headers, row_values)

            try:
                if sheet_name == "Categories":
                    name = _safe_str(row_data.get("name"))
                    if not name:
                        _add_error(import_job, sheet_name, excel_row_number, "name", "Category name is required.")
                        row_has_error = True

                elif sheet_name == "Units":
                    name = _safe_str(row_data.get("name"))
                    if not name:
                        _add_error(import_job, sheet_name, excel_row_number, "name", "Unit name is required.")
                        row_has_error = True

                elif sheet_name == "Customers":
                    name = _safe_str(row_data.get("name"))
                    if not name:
                        _add_error(import_job, sheet_name, excel_row_number, "name", "Customer name cannot be empty.")
                        row_has_error = True

                    email = _safe_str(row_data.get("email"))
                    if email and "@" not in email:
                        _add_error(import_job, sheet_name, excel_row_number, "email", "Email format is invalid.")
                        row_has_error = True

                    points = row_data.get("points")
                    try:
                        if points not in ("", None):
                            parsed_points = _safe_int(points)
                            if parsed_points < 0:
                                raise ValueError("Points cannot be negative.")
                    except Exception as e:
                        _add_error(import_job, sheet_name, excel_row_number, "points", str(e))
                        row_has_error = True

                elif sheet_name == "Suppliers":
                    name = _safe_str(row_data.get("name"))
                    if not name:
                        _add_error(import_job, sheet_name, excel_row_number, "name", "Supplier name is required.")
                        row_has_error = True

                    email = _safe_str(row_data.get("email"))
                    if email and "@" not in email:
                        _add_error(import_job, sheet_name, excel_row_number, "email", "Email format is invalid.")
                        row_has_error = True

                elif sheet_name == "Products":
                    name = _safe_str(row_data.get("name"))
                    code = _safe_str(row_data.get("code"))
                    item_type = _safe_str(row_data.get("item_type")).lower() or "product"

                    if not name:
                        _add_error(import_job, sheet_name, excel_row_number, "name", "Product name is required.")
                        row_has_error = True

                    if not code:
                        _add_error(import_job, sheet_name, excel_row_number, "code", "Product code is required.")
                        row_has_error = True

                    if item_type not in {"product", "menu", "service", "sparepart"}:
                        _add_error(import_job, sheet_name, excel_row_number, "item_type", "Invalid item type.")
                        row_has_error = True

                    try:
                        buy_price = _safe_decimal(row_data.get("buy_price"), default=0)
                        if buy_price < 0:
                            raise ValueError("Buy price cannot be negative.")
                    except Exception as e:
                        _add_error(import_job, sheet_name, excel_row_number, "buy_price", str(e))
                        row_has_error = True

                    try:
                        sell_price = _safe_decimal(row_data.get("sell_price"), default=0)
                        if sell_price < 0:
                            raise ValueError("Selling price cannot be negative.")
                    except Exception as e:
                        _add_error(import_job, sheet_name, excel_row_number, "sell_price", str(e))
                        row_has_error = True

                    try:
                        stock = _safe_int(row_data.get("stock"), default=0)
                        if stock < 0:
                            raise ValueError("Stock cannot be negative.")
                    except Exception as e:
                        _add_error(import_job, sheet_name, excel_row_number, "stock", str(e))
                        row_has_error = True

                elif sheet_name == "OpeningStock":
                    product_code = _safe_str(row_data.get("product_code"))
                    if not product_code:
                        _add_error(import_job, sheet_name, excel_row_number, "product_code", "Product code is required.")
                        row_has_error = True

                    try:
                        qty = _safe_int(row_data.get("quantity"))
                        if qty < 0:
                            raise ValueError("Quantity cannot be negative.")
                    except Exception as e:
                        _add_error(import_job, sheet_name, excel_row_number, "quantity", str(e))
                        row_has_error = True

            except Exception as e:
                _add_error(import_job, sheet_name, excel_row_number, "", str(e))
                row_has_error = True

            if row_has_error:
                invalid_rows += 1
            else:
                valid_rows += 1

    import_job.mark_validated(
        total_rows=total_rows,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        note="Validation preview generated.",
        metadata={
            "detected_sheets": wb.sheetnames,
            "template_sheets": list(TEMPLATE_SHEETS.keys()),
        },
    )

    return {
        "import_job_id": import_job.id,
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "errors": list(import_job.row_errors.all()),
    }


# =========================================================
# IMPORT EXECUTION
# =========================================================
def _latest_successful_backup_exists(shop, hours=24):
    cutoff = timezone.now() - timezone.timedelta(hours=hours)
    return BackupHistory.objects.filter(
        shop=shop,
        status=BackupHistory.Status.SUCCESS,
        deleted_at__isnull=True,
        completed_at__gte=cutoff,
    ).exists()


@transaction.atomic
def run_import(import_job: ImportJob, *, confirm_import: bool, skip_backup_check: bool = False):
    if not confirm_import:
        raise ValueError("Import confirmation is required.")

    if import_job.status not in {ImportJob.Status.VALIDATED, ImportJob.Status.UPLOADED}:
        raise ValueError("Import job must be uploaded or validated before import.")

    if import_job.status == ImportJob.Status.UPLOADED:
        validate_import_workbook(import_job)

    if import_job.invalid_rows > 0:
        raise ValueError("Import cannot continue because invalid rows still exist.")

    if not skip_backup_check and not _latest_successful_backup_exists(import_job.shop):
        raise ValueError("No recent successful backup found. Please create a backup before import.")

    import_job.mark_importing()

    wb = load_workbook(import_job.file.path, data_only=True)
    shop = import_job.shop

    category_map = {}
    unit_map = {}
    supplier_map = {}
    product_map = {}

    imported_rows = 0
    skipped_rows = 0

    # Categories
    if "Categories" in wb.sheetnames:
        ws = wb["Categories"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["Categories"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue
                data = _row_to_dict(headers, row)
                name = _safe_str(data.get("name"))
                obj, created = Category.objects.get_or_create(shop=shop, name=name)
                category_map[name.lower()] = obj
                imported_rows += 1 if created else 0
                skipped_rows += 0 if created else 1

    # Units
    if "Units" in wb.sheetnames:
        ws = wb["Units"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["Units"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue
                data = _row_to_dict(headers, row)
                name = _safe_str(data.get("name"))
                obj, created = Unit.objects.get_or_create(shop=shop, name=name)
                unit_map[name.lower()] = obj
                imported_rows += 1 if created else 0
                skipped_rows += 0 if created else 1

    # Suppliers
    if "Suppliers" in wb.sheetnames:
        ws = wb["Suppliers"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["Suppliers"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue
                data = _row_to_dict(headers, row)
                name = _safe_str(data.get("name"))
                obj, created = Supplier.objects.get_or_create(
                    shop=shop,
                    name=name,
                    defaults={
                        "contact_person": _safe_str(data.get("contact_person")),
                        "cell": _safe_str(data.get("cell")),
                        "email": _safe_str(data.get("email")) or None,
                        "address": _safe_str(data.get("address")),
                    },
                )
                supplier_map[name.lower()] = obj
                imported_rows += 1 if created else 0
                skipped_rows += 0 if created else 1

    # Customers
    if "Customers" in wb.sheetnames:
        ws = wb["Customers"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["Customers"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue
                data = _row_to_dict(headers, row)
                name = _safe_str(data.get("name"))
                defaults = {
                    "cell": _safe_str(data.get("cell")),
                    "email": _safe_str(data.get("email")) or None,
                    "address": _safe_str(data.get("address")),
                    "points": _safe_int(data.get("points"), default=0),
                }
                obj, created = Customer.objects.get_or_create(
                    shop=shop,
                    name=name,
                    defaults=defaults,
                )
                imported_rows += 1 if created else 0
                skipped_rows += 0 if created else 1

    # Products
    if "Products" in wb.sheetnames:
        ws = wb["Products"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["Products"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue

                data = _row_to_dict(headers, row)
                code = _safe_str(data.get("code"))
                name = _safe_str(data.get("name"))
                category_name = _safe_str(data.get("category")).lower()
                unit_name = _safe_str(data.get("unit")).lower()
                supplier_name = _safe_str(data.get("supplier")).lower()

                category = category_map.get(category_name) if category_name else None
                unit = unit_map.get(unit_name) if unit_name else None
                supplier = supplier_map.get(supplier_name) if supplier_name else None

                defaults = {
                    "name": name,
                    "sku": _safe_str(data.get("sku")) or None,
                    "item_type": _safe_str(data.get("item_type")).lower() or "product",
                    "category": category,
                    "unit": unit,
                    "supplier": supplier,
                    "description": _safe_str(data.get("description")),
                    "stock": _safe_int(data.get("stock"), default=0),
                    "track_stock": _safe_bool(data.get("track_stock"), default=True),
                    "buy_price": _safe_decimal(data.get("buy_price"), default=0),
                    "sell_price": _safe_decimal(data.get("sell_price"), default=0),
                    "weight": 0,
                    "is_active": _safe_bool(data.get("is_active"), default=True),
                }

                obj, created = Product.objects.get_or_create(
                    shop=shop,
                    code=code,
                    defaults=defaults,
                )

                if not created:
                    # update field dasar kalau product sudah ada
                    obj.name = defaults["name"]
                    obj.sku = defaults["sku"]
                    obj.item_type = defaults["item_type"]
                    obj.category = defaults["category"]
                    obj.unit = defaults["unit"]
                    obj.supplier = defaults["supplier"]
                    obj.description = defaults["description"]
                    obj.track_stock = defaults["track_stock"]
                    obj.buy_price = defaults["buy_price"]
                    obj.sell_price = defaults["sell_price"]
                    obj.is_active = defaults["is_active"]
                    obj.save()

                product_map[obj.code.lower()] = obj
                imported_rows += 1 if created else 0
                skipped_rows += 0 if created else 1

    # Opening stock
    if "OpeningStock" in wb.sheetnames:
        ws = wb["OpeningStock"]
        headers = _sheet_headers(ws)
        if headers == TEMPLATE_SHEETS["OpeningStock"]:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not any(v not in ("", None) for v in row or []):
                    continue

                data = _row_to_dict(headers, row)
                product_code = _safe_str(data.get("product_code")).lower()
                qty = _safe_int(data.get("quantity"), default=0)

                product = product_map.get(product_code)
                if not product:
                    # fallback cek db
                    product = Product.objects.filter(shop=shop, code__iexact=product_code).first()

                if product:
                    before_stock = product.stock
                    after_stock = qty
                    product.stock = after_stock
                    product.save(update_fields=["stock"])

                    StockMovement.objects.create(
                        shop=shop,
                        product=product,
                        movement_type=StockMovement.Type.ADJUSTMENT,
                        quantity_delta=after_stock - before_stock,
                        before_stock=before_stock,
                        after_stock=after_stock,
                        note=f"Opening stock import #{import_job.id}",
                        ref_model="ImportJob",
                        ref_id=import_job.id,
                        created_by=import_job.uploaded_by,
                    )
                    imported_rows += 1

    import_job.mark_completed(
        imported_rows=imported_rows,
        skipped_rows=skipped_rows,
        note="Master data import completed successfully.",
        metadata={
            **(import_job.metadata or {}),
            "imported_at": timezone.localtime().isoformat(),
        },
    )

    return import_job