def user_role_context(request):
    if request.user.is_authenticated:
        return {"user_role": request.user.role_label}
    return {"user_role": None}