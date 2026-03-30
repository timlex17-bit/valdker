# pos/permissions_import.py

from rest_framework.permissions import BasePermission, SAFE_METHODS


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


def _is_tenant_owner(user):
    return bool(_is_tenant_user(user) and _is_owner(user))


def _is_tenant_manager(user):
    return bool(_is_tenant_user(user) and _is_manager(user))


def _same_shop(user, obj):
    user_shop_id = getattr(user, "shop_id", None)
    obj_shop_id = getattr(obj, "shop_id", None)
    return bool(user_shop_id and obj_shop_id and user_shop_id == obj_shop_id)


class ImportTemplatePermission(BasePermission):
    """
    Download template:
    owner, manager, platform admin
    """
    message = "You do not have permission to download import template."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not _is_authenticated(user):
            return False
        if _is_platform_admin(user):
            return True
        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))


class ImportJobPermission(BasePermission):
    """
    Upload/list/detail/validate:
    owner, manager, platform admin

    confirm import:
    owner, platform admin
    """
    message = "You do not have permission to access import jobs."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not _is_authenticated(user):
            return False

        if _is_platform_admin(user):
            return True

        action_name = getattr(view, "action_name", "")

        if action_name == "confirm":
            return _is_tenant_owner(user)

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)

        if _is_platform_admin(user):
            return True

        if not _same_shop(user, obj):
            return False

        action_name = getattr(view, "action_name", "")

        if action_name == "confirm":
            return _is_tenant_owner(user)

        return bool(_is_tenant_owner(user) or _is_tenant_manager(user))