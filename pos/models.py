from django.db import models
from django.conf import settings
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import AbstractUser


# ========== CUSTOM USER ==========
class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('cashier', 'Cashier'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='cashier')
    
    @property
    def role_label(self):
        if self.is_superuser:
            return 'admin'
        return self.role

# ========== 1. CUSTOMER ==========
class Customer(models.Model):
    name = models.CharField(max_length=100)
    cell = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name

# ========== 2. SUPPLIER ==========
class Supplier(models.Model):
    name = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100)
    cell = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.name

# ========== 3. CATEGORY & UNITS ==========
class Category(models.Model):
    name = models.CharField(max_length=100)
    icon = models.ImageField(upload_to='category_icons/', null=True, blank=True)

    def __str__(self):
        return self.name

class Unit(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

# ========== 4. PRODUCT ==========
class Product(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    description = models.TextField(blank=True)
    stock = models.IntegerField()
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    weight = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Berat produk dalam satuan kilogram (kg). Contoh: 1.00 untuk 1kg."
    )
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True)
    image = models.ImageField(upload_to='product_images/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

# ========== 5. ORDER & CART ==========
class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    payment_method = models.CharField(max_length=50, choices=[
        ('cash', 'Cash'), ('card', 'Card'), ('qris', 'QRIS')
    ])
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    is_paid = models.BooleanField(default=True)
    
    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    )

    def __str__(self):
        return f"Order #{self.id}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    weight_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

# ========== 6. EXPENSE ==========
class Expense(models.Model):
    name = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    time = models.TimeField()

    def __str__(self):
        return self.name

# ========== 7. SETTINGS ==========
class Shop(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    logo = models.ImageField(upload_to='shop_logos/', blank=True, null=True)

    def __str__(self):
        return self.name
    
# ========== 8. SLIDE BANNER ==========
class Banner(models.Model):
    title = models.CharField(max_length=100)
    image = models.ImageField(upload_to='banners/')
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.title
    
class TokenProxy(Token):
    class Meta:
        proxy = True
        app_label = "pos"
        verbose_name = "Token"
        verbose_name_plural = "Tokens"