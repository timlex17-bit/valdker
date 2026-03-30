from rest_framework.exceptions import ValidationError, PermissionDenied

from pos.models import Shop

try:
    from pos.models import ShopStaff
except Exception:
    ShopStaff = None


ALLOWED_OWNER_CHAT_ROLES = {"owner", "admin", "manager"}


def get_request_shop_code(request):
    return (
        request.headers.get("X-Shop-Code")
        or request.data.get("shop_code")
        or request.query_params.get("shop_code")
    )


def _get_user_role(user):
    return (getattr(user, "role", "") or "").lower().strip()


def resolve_shop_for_user(request):
    """
    Resolve active shop from:
    1. X-Shop-Code header / request body / query param
    2. request.user.shop_id
    3. ShopStaff relation (if model exists)

    Raises ValidationError / PermissionDenied when invalid.
    """
    user = request.user
    shop_code = get_request_shop_code(request)

    # 1) Explicit shop_code
    if shop_code:
        try:
            shop = Shop.objects.get(code=shop_code, is_active=True)
        except Shop.DoesNotExist:
            raise ValidationError({"shop_code": "Shop tidak ditemukan / tidak aktif."})

        if getattr(user, "is_superuser", False):
            return shop

        # direct relation on user
        if getattr(user, "shop_id", None) == shop.id:
            return shop

        # ShopStaff relation if available
        if ShopStaff is not None:
            has_access = ShopStaff.objects.filter(
                user=user,
                shop=shop,
                is_active=True
            ).exists()
            if has_access:
                return shop

        raise PermissionDenied("Anda tidak punya akses ke shop ini.")

    # 2) fallback from user.shop_id
    user_shop_id = getattr(user, "shop_id", None)
    if user_shop_id:
        try:
            return Shop.objects.get(id=user_shop_id, is_active=True)
        except Shop.DoesNotExist:
            raise ValidationError({"shop": "Shop user tidak valid / tidak aktif."})

    # 3) fallback from ShopStaff if only one active shop
    if ShopStaff is not None:
        staff_qs = (
            ShopStaff.objects
            .filter(user=user, is_active=True, shop__is_active=True)
            .select_related("shop")
        )

        count = staff_qs.count()
        if count == 1:
            return staff_qs.first().shop
        if count > 1:
            raise ValidationError({"shop_code": "User punya lebih dari satu shop. Kirim X-Shop-Code."})

    raise ValidationError({"shop_code": "shop_code wajib dikirim atau user belum terhubung ke shop."})


def validate_owner_chat_role(user, shop):
    """
    Validate role allowed to access owner chat.
    Superuser is always allowed.
    """
    if getattr(user, "is_superuser", False):
        return True

    role = _get_user_role(user)
    if role in ALLOWED_OWNER_CHAT_ROLES:
        return True

    # optional strict role check from ShopStaff if role stored there
    if ShopStaff is not None:
        staff = (
            ShopStaff.objects
            .filter(user=user, shop=shop, is_active=True)
            .first()
        )
        if staff:
            staff_role = (getattr(staff, "role", "") or "").lower().strip()
            if staff_role in ALLOWED_OWNER_CHAT_ROLES:
                return True

    raise PermissionDenied("Fitur ini hanya untuk owner/admin/manager.")