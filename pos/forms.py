from django import forms
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from pos.models import Shop

User = get_user_model()


class ShopAdminForm(forms.ModelForm):
    """
    Form admin untuk create Shop + onboarding owner.
    Extra fields ini TIDAK disimpan ke model Shop langsung.
    Akan dipakai oleh ShopProvisionService.
    """

    owner_full_name = forms.CharField(
        required=False,
        label="Owner full name",
    )

    owner_username = forms.CharField(
        required=False,
        label="Owner username",
        help_text="Username untuk tenant owner toko.",
    )

    owner_email = forms.EmailField(
        required=False,
        label="Owner email",
    )

    owner_password1 = forms.CharField(
        required=False,
        label="Owner password",
        widget=forms.PasswordInput(render_value=False),
    )

    owner_password2 = forms.CharField(
        required=False,
        label="Confirm owner password",
        widget=forms.PasswordInput(render_value=False),
    )

    provision_defaults = forms.BooleanField(
        required=False,
        initial=True,
        label="Auto provision default tenant data",
        help_text="Create owner, payment methods, category, unit, warehouse, POS settings, roles, and permissions.",
    )

    class Meta:
        model = Shop
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        is_edit = bool(self.instance and self.instance.pk)

        # Saat create baru, owner fields wajib
        if not is_edit:
            self.fields["owner_username"].required = True
            self.fields["owner_password1"].required = True
            self.fields["owner_password2"].required = True

        # Saat edit, field password opsional
        else:
            self.fields["owner_password1"].help_text = "Kosongkan jika tidak ingin mengganti password owner."
            self.fields["owner_password2"].help_text = "Kosongkan jika tidak ingin mengganti password owner."

        # Kalau field owner ada di form model, kita biarkan readonly via admin,
        # bukan di form ini.

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        return code

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip()
        name = (self.cleaned_data.get("name") or "").strip()
        code = (self.cleaned_data.get("code") or "").strip()

        if not slug:
            source = code or name
            slug = slugify(source)

        return slug

    def clean_owner_username(self):
        username = (self.cleaned_data.get("owner_username") or "").strip()

        # waktu edit, field ini boleh kosong
        if not username and self.instance and self.instance.pk:
            return username

        if not username:
            return username

        existing = User.objects.filter(username=username)

        # kalau edit shop dan owner existing pakai username yang sama, biarkan
        if self.instance and self.instance.pk and getattr(self.instance, "owner_id", None):
            existing = existing.exclude(pk=self.instance.owner_id)

        if existing.exists():
            raise forms.ValidationError("Username owner sudah dipakai. Gunakan username lain.")

        return username

    def clean(self):
        cleaned = super().clean()

        is_edit = bool(self.instance and self.instance.pk)

        password1 = cleaned.get("owner_password1")
        password2 = cleaned.get("owner_password2")
        owner_username = cleaned.get("owner_username")
        provision_defaults = cleaned.get("provision_defaults")

        if not is_edit and provision_defaults:
            if not owner_username:
                self.add_error("owner_username", "Owner username wajib diisi.")
            if not password1:
                self.add_error("owner_password1", "Owner password wajib diisi.")
            if not password2:
                self.add_error("owner_password2", "Konfirmasi password wajib diisi.")

        # validasi password cocok
        if password1 or password2:
            if password1 != password2:
                self.add_error("owner_password2", "Konfirmasi password tidak sama.")

        return cleaned