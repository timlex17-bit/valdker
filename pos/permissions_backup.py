# pos/permissions_backup.py

from rest_framework.permissions import BasePermission, SAFE_METHODS


# =========================================================
# HELPERS
# =========================================================
def _user_role(user):
    return (getattr(user, "role", "") or "").lower().strip()


def _is_authenticated(user):
    return bool(user and user.is_authenticated)


def _is_platform_admin(user):
    return bool(_is_authenticated(user) and getattr(user, "is_superuser", False))


def _has_shop(user):
    return bool(getattr(user, "shop_id", None))


def _is_tenant_user(user):
    return bool(_is_authenticated(user) and not _is_platform_admin(user) and _has_shop(user))


def _is_owner(user):
    return _user_role(user) == "owner"


def _is_manager(user):
    return _user_role(user) == "manager"


def _is_cashier(user):
    return _user_role(user) == "cashier"


def _is_tenant_owner(user):
    return bool(_is_tenant_user(user) and _is_owner(user))


def _is_tenant_manager(user):
    return bool(_is_tenant_user(user) and _is_manager(user))


def _same_shop(user, obj):
    user_shop_id = getattr(user, "shop_id", None)
    obj_shop_id = getattr(obj, "shop_id", None)
    return bool(user_shop_id and obj_shop_id and user_shop_id == obj_shop_id)


# =========================================================
# BACKUP SETTINGS PERMISSION
# =========================================================
class BackupSettingPermission(BasePermission):
    """
    GET:
        owner, manager, platform admin

    PUT/PATCH:
        owner, platform admin
    """

    message = "You do not have permission to access backup settings."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        if request.method in SAFE_METHODS:
            return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

        return _is_tenant_owner(user)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        if not _same_shop(user, obj):
            return False

        if request.method in SAFE_METHODS:
            return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

        return _is_tenant_owner(user)


# =========================================================
# BACKUP SUMMARY PERMISSION
# =========================================================
class BackupSummaryPermission(BasePermission):
    """
    GET:
        owner, manager, platform admin
    """

    message = "You do not have permission to view backup summary."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


# =========================================================
# BACKUP HISTORY PERMISSION
# =========================================================
class BackupHistoryPermission(BasePermission):
    """
    LIST / DETAIL / DOWNLOAD:
        owner, manager, platform admin

    DELETE:
        owner, platform admin
    """

    message = "You do not have permission to access backup history."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        if request.method in SAFE_METHODS:
            return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

        return _is_tenant_owner(user)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        if not _same_shop(user, obj):
            return False

        if request.method in SAFE_METHODS:
            return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

        return _is_tenant_owner(user)


# =========================================================
# RUN BACKUP PERMISSION
# =========================================================
class BackupRunPermission(BasePermission):
    """
    POST:
        owner, manager, platform admin
    """

    message = "You do not have permission to run backup."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


# =========================================================
# RESTORE PERMISSION
# =========================================================
class BackupRestorePermission(BasePermission):
    """
    POST restore:
        owner, platform admin
    """

    message = "You do not have permission to restore backup."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return _is_tenant_owner(user)

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        return _same_shop(user, obj) and _is_tenant_owner(user)


# =========================================================
# RESTORE HISTORY PERMISSION
# =========================================================
class RestoreHistoryPermission(BasePermission):
    """
    GET:
        owner, manager, platform admin
    """

    message = "You do not have permission to view restore history."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)

        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        return _same_shop(user, obj) and bool(_is_tenant_owner(user) or _is_tenant_manager(user))