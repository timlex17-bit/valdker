from rest_framework.permissions import BasePermission


class IsOwnerOrManager(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser or user.is_staff:
            return True

        role = getattr(user, "role", None)
        if role:
            r = str(role).lower()
            if r in ("owner", "manager", "admin"):
                return True

        if user.groups.filter(name__in=["Owner", "Manager", "Admin"]).exists():
            return True

        return False