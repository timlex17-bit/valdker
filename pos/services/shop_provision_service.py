from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from pos.models import Shop, Category, Unit, PaymentMethod

try:
    from pos.models import Warehouse
except ImportError:
    Warehouse = None

try:
    from pos.models import POSSettings as POSSettingsModel
except ImportError:
    try:
        from pos.models import PosSetting as POSSettingsModel
    except ImportError:
        POSSettingsModel = None


User = get_user_model()


class ShopProvisionService:
    @classmethod
    @transaction.atomic
    def provision(
        cls,
        *,
        shop: Shop,
        owner_username: str,
        owner_email: str = "",
        owner_password: str,
        owner_full_name: str = "",
        created_by=None,
    ):
        if not shop.pk:
            raise ValueError("Shop must be saved before provisioning.")

        owner = cls._ensure_owner(
            shop=shop,
            username=owner_username,
            email=owner_email,
            password=owner_password,
            full_name=owner_full_name,
        )

        cls._ensure_default_categories(shop=shop)
        cls._ensure_default_units(shop=shop)
        cls._ensure_default_payment_methods(shop=shop)
        cls._ensure_default_pos_settings(shop=shop)
        cls._ensure_default_warehouse(shop=shop)

        groups = cls._ensure_default_groups_and_permissions(shop=shop)
        cls._assign_owner_group(owner=owner, groups=groups)

        if hasattr(shop, "owner") and shop.owner_id != owner.id:
            shop.owner = owner
            shop.save(update_fields=["owner"])

        return {
            "shop": shop,
            "owner": owner,
            "groups": groups,
        }

    @classmethod
    def _ensure_owner(cls, *, shop, username, email, password, full_name=""):
        """
        Buat / sinkronkan owner tenant.
        Owner tenant dipetakan ke role = owner.
        """
        user = User.objects.filter(username=username).first()

        if user is None:
            user = User(
                username=username,
                **cls._build_user_defaults(
                    shop=shop,
                    email=email,
                    full_name=full_name,
                ),
            )
            user.set_password(password)

            if hasattr(user, "is_active"):
                user.is_active = True

            user.save()
            return user

        cls._apply_user_shop(user, shop)
        cls._apply_user_email(user, email)
        cls._apply_user_full_name(user, full_name)
        cls._apply_user_role_owner(user)

        if password:
            user.set_password(password)

        if hasattr(user, "is_active"):
            user.is_active = True

        user.save()
        return user

    @classmethod
    def _build_user_defaults(cls, *, shop, email="", full_name=""):
        defaults = {}

        if cls._user_has_field("email"):
            defaults["email"] = email or ""

        if cls._user_has_field("is_active"):
            defaults["is_active"] = True

        if cls._user_has_field("shop"):
            defaults["shop"] = shop

        if cls._user_has_field("role"):
            defaults["role"] = getattr(User, "ROLE_OWNER", "owner")

        if cls._user_has_field("full_name"):
            defaults["full_name"] = full_name or ""
        elif full_name:
            first_name, last_name = cls._split_full_name(full_name)
            if cls._user_has_field("first_name"):
                defaults["first_name"] = first_name
            if cls._user_has_field("last_name"):
                defaults["last_name"] = last_name

        return defaults

    @classmethod
    def _apply_user_shop(cls, user, shop):
        if hasattr(user, "shop"):
            user.shop = shop

    @classmethod
    def _apply_user_email(cls, user, email):
        if email and hasattr(user, "email"):
            user.email = email

    @classmethod
    def _apply_user_full_name(cls, user, full_name):
        if not full_name:
            return

        if hasattr(user, "full_name"):
            user.full_name = full_name
            return

        first_name, last_name = cls._split_full_name(full_name)

        if hasattr(user, "first_name"):
            user.first_name = first_name

        if hasattr(user, "last_name"):
            user.last_name = last_name

    @classmethod
    def _apply_user_role_owner(cls, user):
        if hasattr(user, "role"):
            user.role = getattr(User, "ROLE_OWNER", "owner")

    @classmethod
    def _split_full_name(cls, full_name):
        parts = (full_name or "").strip().split()
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    @classmethod
    def _user_has_field(cls, field_name):
        return any(f.name == field_name for f in User._meta.get_fields())

    @classmethod
    def _ensure_default_categories(cls, *, shop):
        Category.objects.get_or_create(
            shop=shop,
            name="General",
        )

    @classmethod
    def _ensure_default_units(cls, *, shop):
        Unit.objects.get_or_create(
            shop=shop,
            name="PCS",
        )

    @classmethod
    def _ensure_default_payment_methods(cls, *, shop):
        items = [
            {
                "name": "Cash",
                "code": "CASH",
                "payment_type": PaymentMethod.PaymentType.CASH,
                "requires_bank_account": False,
                "is_active": True,
                "note": "Default payment method: Cash",
            },
            {
                "name": "QRIS",
                "code": "QRIS",
                "payment_type": PaymentMethod.PaymentType.QRIS,
                "requires_bank_account": True,
                "is_active": True,
                "note": "Default payment method: QRIS",
            },
            {
                "name": "Bank",
                "code": "BANK",
                "payment_type": PaymentMethod.PaymentType.BANK,
                "requires_bank_account": True,
                "is_active": True,
                "note": "Default payment method: Bank Transfer",
            },
        ]

        for item in items:
            obj, created = PaymentMethod.objects.get_or_create(
                shop=shop,
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "payment_type": item["payment_type"],
                    "requires_bank_account": item["requires_bank_account"],
                    "is_active": item["is_active"],
                    "note": item["note"],
                },
            )

            updates = []

            if obj.name != item["name"]:
                obj.name = item["name"]
                updates.append("name")

            if obj.payment_type != item["payment_type"]:
                obj.payment_type = item["payment_type"]
                updates.append("payment_type")

            if obj.requires_bank_account != item["requires_bank_account"]:
                obj.requires_bank_account = item["requires_bank_account"]
                updates.append("requires_bank_account")

            if obj.is_active is not item["is_active"]:
                obj.is_active = item["is_active"]
                updates.append("is_active")

            if obj.note != item["note"]:
                obj.note = item["note"]
                updates.append("note")

            if updates:
                obj.save(update_fields=updates)

    @classmethod
    def _ensure_default_pos_settings(cls, *, shop):
        if POSSettingsModel is None:
            return

        field_names = cls._model_field_names(POSSettingsModel)
        defaults = {}

        if "receipt_footer" in field_names:
            defaults["receipt_footer"] = "Thank you for shopping"
        if "currency" in field_names:
            defaults["currency"] = "USD"
        if "currency_symbol" in field_names:
            defaults["currency_symbol"] = "$"
        if "decimal_places" in field_names:
            defaults["decimal_places"] = 2
        if "enable_stock_alert" in field_names:
            defaults["enable_stock_alert"] = True
        if "low_stock_threshold" in field_names:
            defaults["low_stock_threshold"] = 5
        if "allow_negative_stock" in field_names:
            defaults["allow_negative_stock"] = False
        if "tax_percent" in field_names:
            defaults["tax_percent"] = 0
        if "invoice_prefix" in field_names:
            defaults["invoice_prefix"] = f"{shop.code}-" if shop.code else "SHOP-"
        if "is_active" in field_names:
            defaults["is_active"] = True

        POSSettingsModel.objects.get_or_create(
            shop=shop,
            defaults=defaults,
        )

    @classmethod
    def _ensure_default_warehouse(cls, *, shop):
        if Warehouse is None:
            return

        field_names = cls._model_field_names(Warehouse)

        lookup = {"shop": shop}
        defaults = {}

        if "code" in field_names:
            lookup["code"] = "MAIN"
            defaults["name"] = "Main Warehouse"
        elif "name" in field_names:
            lookup["name"] = "Main Warehouse"
        else:
            return

        if "code" in field_names:
            defaults["code"] = "MAIN"
        if "name" in field_names:
            defaults["name"] = "Main Warehouse"
        if "is_active" in field_names:
            defaults["is_active"] = True
        if "address" in field_names:
            defaults["address"] = ""
        if "description" in field_names:
            defaults["description"] = "Default warehouse for new shop"

        Warehouse.objects.get_or_create(
            **lookup,
            defaults=defaults,
        )

    @classmethod
    def _ensure_default_groups_and_permissions(cls, *, shop):
        prefix = (shop.code or f"SHOP{shop.id}").upper().strip()

        owner_group, _ = Group.objects.get_or_create(name=f"{prefix}__OWNER")
        manager_group, _ = Group.objects.get_or_create(name=f"{prefix}__MANAGER")
        cashier_group, _ = Group.objects.get_or_create(name=f"{prefix}__CASHIER")

        pos_permissions = list(
            Permission.objects.filter(content_type__app_label="pos")
        )

        owner_group.permissions.set(pos_permissions)

        manager_permissions = [
            p for p in pos_permissions
            if p.codename.startswith("view_")
            or p.codename.startswith("add_")
            or p.codename.startswith("change_")
        ]
        manager_group.permissions.set(manager_permissions)

        cashier_suffixes = {
            "order",
            "orderitem",
            "customer",
            "product",
            "paymentmethod",
            "category",
            "unit",
        }

        cashier_permissions = [
            p for p in pos_permissions
            if (
                p.codename.startswith("view_")
                or p.codename.startswith("add_")
                or p.codename.startswith("change_")
            )
            and any(p.codename.endswith(f"_{suffix}") for suffix in cashier_suffixes)
        ]
        cashier_group.permissions.set(cashier_permissions)

        return {
            "owner_group": owner_group,
            "manager_group": manager_group,
            "cashier_group": cashier_group,
        }

    @classmethod
    def _assign_owner_group(cls, *, owner, groups):
        owner_group = groups.get("owner_group")
        if owner_group:
            owner.groups.add(owner_group)

    @classmethod
    def _model_field_names(cls, model):
        return {f.name for f in model._meta.get_fields()}