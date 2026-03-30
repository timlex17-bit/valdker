from rest_framework.permissions import BasePermission


class IsOwnerOrManager(BasePermission):

    def has_permission(self, request, view):

        user = request.user

        if not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        role = (getattr(user,"role","") or "").lower()

        return role in [
            "owner",
            "manager"
        ]