from functools import wraps
from django.shortcuts import redirect


def role_required(roles):
    normalized_roles = [(r or "").lower().strip() for r in roles]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = getattr(request, "user", None)

            if not user or not user.is_authenticated:
                return redirect("/admin/login/")

            if user.is_superuser:
                return view_func(request, *args, **kwargs)

            user_role = (getattr(user, "role", "") or "").lower().strip()
            if user_role in normalized_roles:
                return view_func(request, *args, **kwargs)

            return redirect("/admin/")
        return _wrapped_view
    return decorator