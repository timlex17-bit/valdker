# pos/permissions.py
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSuperAdminOnly(BasePermission):
    """
    ONLY allow superuser.
    Our policy: role ADMIN == is_superuser True.
    """
    message = "Admin only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_superuser)


class AdminOnlyWriteOrRead(BasePermission):
    """
    Allow READ (GET/HEAD/OPTIONS) for any authenticated user,
    but only superadmin can WRITE (POST/PUT/PATCH/DELETE).
    """
    message = "Write access is admin only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return bool(user.is_superuser)


class AdminOrManagerWriteOrRead(BasePermission):
    """
    Allow READ (GET/HEAD/OPTIONS) for any authenticated user,
    but only superadmin OR role manager can WRITE (POST/PUT/PATCH/DELETE).
    """
    message = "Write access is admin/manager only."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        # superadmin always allowed
        if user.is_superuser:
            return True

        role = (getattr(user, "role", "") or "").lower().strip()
        return role in ("manager", "admin")

# ---------------------------------------------------------
# Keep legacy permission name so imports won't crash.
# Previously: IsOwnerOrManager existed in your project.
# Now OwnerChat must be Admin-only, but other modules may still import this.
# We keep it permissive for old usage (or you can delete later).
# ---------------------------------------------------------
class IsOwnerOrManager(BasePermission):
    """
    Legacy compatibility.
    Historically allowed owner/manager/admin.
    We'll keep behavior but NOT use this for OwnerChat anymore.
    """
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        role = getattr(user, "role", "") or ""
        role = role.lower().strip()
        if role in ("admin", "manager"):
            return True

        return False