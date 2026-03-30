from rest_framework.permissions import BasePermission, SAFE_METHODS


# =========================================================
# BASIC HELPERS
# =========================================================

def _user_role(user):
    return (getattr(user, "role", "") or "").lower().strip()


def _is_authenticated(user):
    return bool(user and user.is_authenticated)


def _has_shop(user):
    return bool(getattr(user, "shop_id", None))


def _is_platform_admin(user):
    return bool(_is_authenticated(user) and user.is_superuser)


def _is_owner(user):
    return _user_role(user) == "owner"


def _is_admin(user):
    return _user_role(user) == "admin"


def _is_manager(user):
    return _user_role(user) == "manager"


def _is_cashier(user):
    return _user_role(user) == "cashier"


def _is_owner_admin_manager(user):
    return _user_role(user) in ("owner", "admin", "manager")


def _is_tenant_user(user):
    """
    Tenant user harus:
    - authenticated
    - bukan platform admin
    - punya shop_id
    """
    return bool(_is_authenticated(user) and not _is_platform_admin(user) and _has_shop(user))


def _is_tenant_owner(user):
    return bool(_is_tenant_user(user) and _is_owner(user))


def _is_tenant_admin(user):
    return bool(_is_tenant_user(user) and _is_admin(user))


def _is_tenant_manager(user):
    return bool(_is_tenant_user(user) and _is_manager(user))


def _is_tenant_cashier(user):
    return bool(_is_tenant_user(user) and _is_cashier(user))


def _is_tenant_owner_admin_manager(user):
    return bool(_is_tenant_user(user) and _is_owner_admin_manager(user))


def _resolve_obj_shop_id(obj):
    """
    Resolve tenant owner shop_id dari object.
    Support beberapa pola umum:
    - obj.shop_id
    - obj.shop.id
    - obj.order.shop_id
    - obj.bank_account.shop_id
    """
    if obj is None:
        return None

    shop_id = getattr(obj, "shop_id", None)
    if shop_id:
        return shop_id

    shop = getattr(obj, "shop", None)
    if shop is not None:
        return getattr(shop, "id", None)

    order = getattr(obj, "order", None)
    if order is not None:
        order_shop_id = getattr(order, "shop_id", None)
        if order_shop_id:
            return order_shop_id

    bank_account = getattr(obj, "bank_account", None)
    if bank_account is not None:
        bank_shop_id = getattr(bank_account, "shop_id", None)
        if bank_shop_id:
            return bank_shop_id

    return None


def _same_shop(user, obj):
    user_shop_id = getattr(user, "shop_id", None)
    obj_shop_id = _resolve_obj_shop_id(obj)

    if not user_shop_id or not obj_shop_id:
        return False

    return user_shop_id == obj_shop_id


# =========================================================
# PLATFORM ADMIN
# =========================================================

class IsPlatformAdminOnly(BasePermission):
    message = "Platform admin only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return _is_platform_admin(user)


# =========================================================
# OWNER WRITE
# =========================================================

class OwnerOnlyWriteOrRead(BasePermission):
    """
    Read:
        any authenticated user

    Write:
        platform admin
        shop owner
    """

    message = "Write access is owner only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if request.method in SAFE_METHODS:
            return True

        if _is_platform_admin(user):
            return True

        return _is_tenant_owner(user)


# =========================================================
# OWNER + MANAGER WRITE
# =========================================================

class OwnerOrManagerWriteOrRead(BasePermission):
    """
    Read:
        any authenticated user

    Write:
        platform admin
        owner
        manager
    """

    message = "Write access is owner/manager only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if request.method in SAFE_METHODS:
            return True

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


# =========================================================
# LEGACY
# =========================================================

class IsOwnerOrManager(BasePermission):
    message = "Owner or manager only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


# =========================================================
# OWNER + MANAGER + PLATFORM
# =========================================================

class IsOwnerOrManagerOrPlatformAdmin(BasePermission):
    message = "Owner, manager, or platform admin only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


# =========================================================
# FINAL MULTI TENANT ROLE
# =========================================================

class IsOwnerManagerAdminOrPlatformAdmin(BasePermission):
    """
    Allowed:
        platform admin
        owner
        admin (tenant)
        manager

    Blocked:
        cashier
        staff
        others
    """

    message = "Owner, admin, manager, or platform admin only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return _is_tenant_owner_admin_manager(user)


# =========================================================
# BANK ACCOUNT PERMISSION
# =========================================================

class BankAccountPermission(BasePermission):
    """
    Owner:
        full CRUD

    Admin tenant:
        read only

    Manager:
        read only

    Cashier:
        read only

    Platform admin:
        read only
    """

    message = "You do not have permission to perform this action on bank accounts."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if request.method in SAFE_METHODS:
            return True

        if _is_platform_admin(user):
            return False

        return _is_tenant_owner(user)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return request.method in SAFE_METHODS

        if not _same_shop(user, obj):
            return False

        if request.method in SAFE_METHODS:
            return True

        return _is_tenant_owner(user)


class ShopStaffPermission(BasePermission):
    """
    Staff per shop:
    - superuser: full access
    - owner: full CRUD untuk staff di shop sendiri
    - manager: read only staff di shop sendiri
    - cashier: tidak boleh akses
    """

    message = "You do not have permission to manage shop staff."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        role = (getattr(user, "role", "") or "").lower().strip()
        has_shop = bool(getattr(user, "shop_id", None))

        if not has_shop:
            return False

        if request.method in SAFE_METHODS:
            return role in {"owner", "manager"}

        return role == "owner"

    def has_object_permission(self, request, view, obj):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        user_shop_id = getattr(user, "shop_id", None)
        obj_shop_id = getattr(obj, "shop_id", None)

        if not user_shop_id or user_shop_id != obj_shop_id:
            return False

        role = (getattr(user, "role", "") or "").lower().strip()

        if request.method in SAFE_METHODS:
            return role in {"owner", "manager"}

        return role == "owner"

# =========================================================
# OPTIONAL GENERIC TENANT OBJECT PERMISSION
# =========================================================

class SameShopObjectPermission(BasePermission):
    """
    Optional helper kalau nanti ingin dipakai di endpoint lain.
    - Platform admin: allow
    - Tenant user: object harus satu shop
    """

    message = "This object does not belong to your shop."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return _is_authenticated(user)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        return _same_shop(user, obj)


# =========================================================
# BACKWARD COMPATIBILITY
# =========================================================

IsSuperAdminOnly = IsPlatformAdminOnly
AdminOnlyWriteOrRead = OwnerOnlyWriteOrRead
AdminOrManagerWriteOrRead = OwnerOrManagerWriteOrRead