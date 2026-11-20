import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

User = settings.AUTH_USER_MODEL


def _unique_slug(instance, source, max_len=190):
    base = slugify(source)[:max_len] or "item"
    slug, n = base, 2
    model = instance.__class__
    while model.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ------------------------------------------------------------------ catalogue
class Category(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    image = models.ImageField(upload_to="categories/", blank=True)
    show_in_nav = models.BooleanField(default=True, help_text="Show this top-level category in the main navigation.")
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.parent.name} / {self.name}" if self.parent else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("ROSA:product_list_category", args=[self.slug])

    @property
    def root(self):
        return self.parent or self


class Size(models.Model):
    name = models.CharField(max_length=20, unique=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Colour(models.Model):
    name = models.CharField(max_length=40, unique=True)
    hex_code = models.CharField(max_length=7, default="#CCCCCC", help_text="e.g. #E58A24")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    brand = models.CharField(max_length=100, default="ROSA")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    description = models.TextField(blank=True)
    price = models.DecimalField("MRP (₹)", max_digits=10, decimal_places=2)
    discount_price = models.DecimalField("Sale price (₹)", max_digits=10, decimal_places=2, null=True, blank=True,
                                         help_text="Leave empty if there is no discount.")
    stock = models.PositiveIntegerField(default=0)
    sizes = models.ManyToManyField(Size, blank=True, related_name="products")
    colours = models.ManyToManyField(Colour, blank=True, related_name="products")
    is_featured = models.BooleanField(default=False, help_text="Shown in 'Trending at ROSA'.")
    is_new_arrival = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, self.name, 210)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("ROSA:product_detail", args=[self.slug])

    @property
    def sale_price(self):
        if self.discount_price is not None and self.discount_price < self.price:
            return self.discount_price
        return self.price

    @property
    def has_discount(self):
        return self.sale_price < self.price

    @property
    def discount_percent(self):
        if not self.has_discount:
            return 0
        return int(round((self.price - self.sale_price) / self.price * 100))

    @property
    def in_stock(self):
        return self.stock > 0

    @property
    def has_options(self):
        return bool(self.sizes.all()) or bool(self.colours.all())

    @property
    def cover(self):
        imgs = list(self.images.all())
        return imgs[0] if imgs else None

    @property
    def hover_image(self):
        imgs = list(self.images.all())
        return imgs[1] if len(imgs) > 1 else None


class ProductImage(models.Model):
    LABELS = [
        ("front", "Front view"),
        ("back", "Back view"),
        ("side", "Side view"),
        ("closeup", "Close-up"),
        ("lifestyle", "Lifestyle view"),
    ]
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")
    label = models.CharField(max_length=20, choices=LABELS, default="front")
    order = models.PositiveSmallIntegerField(default=0, help_text="Leave 0 to order by view type.")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product.name} – {self.get_label_display()}"

    def save(self, *args, **kwargs):
        if not self.order:
            keys = [k for k, _ in self.LABELS]
            self.order = keys.index(self.label) + 1 if self.label in keys else 9
        super().save(*args, **kwargs)


class Promotion(models.Model):
    """Homepage content blocks the administrator controls."""
    HERO = "hero"
    HERO_SECONDARY = "hero_secondary"
    CARD = "card"
    BANNER = "banner"
    PLACEMENTS = [
        (HERO, "Hero – main image"),
        (HERO_SECONDARY, "Hero – small secondary image"),
        (CARD, "Collection card (use 3)"),
        (BANNER, "Full-width banner"),
    ]
    placement = models.CharField(max_length=20, choices=PLACEMENTS)
    kicker = models.CharField(max_length=80, blank=True, help_text="Small line above the title.")
    title = models.CharField(max_length=120)
    text = models.CharField(max_length=240, blank=True)
    button_label = models.CharField(max_length=40, blank=True)
    link_url = models.CharField(max_length=200, blank=True, help_text="e.g. /shop/women/ or /shop/?sale=1")
    image = models.ImageField(upload_to="promotions/", blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["placement", "order", "id"]

    def __str__(self):
        return f"{self.get_placement_display()}: {self.title}"


# ------------------------------------------------------------------ customers
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=20, blank=True)
    picture = models.ImageField(upload_to="profiles/", blank=True)

    def __str__(self):
        return f"Profile of {self.user}"


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    line1 = models.CharField("Address line 1", max_length=200)
    line2 = models.CharField("Address line 2", max_length=200, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    pincode = models.CharField(max_length=10)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_default", "-id"]
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.full_name}, {self.city} {self.pincode}"


class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wishlist")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "product")
        ordering = ["-added_at"]

    def __str__(self):
        return f"{self.user} ♥ {self.product}"


class Subscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


# ------------------------------------------------------------------ cart
class CartItem(models.Model):
    """Owned by a logged-in user, or by an anonymous session until login."""
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="cart_items")
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    size = models.ForeignKey(Size, null=True, blank=True, on_delete=models.SET_NULL)
    colour = models.ForeignKey(Colour, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at"]

    def __str__(self):
        return f"{self.quantity} × {self.product}"

    @property
    def line_total(self):
        return self.product.sale_price * self.quantity

    @property
    def line_mrp(self):
        return self.product.price * self.quantity


# ------------------------------------------------------------------ orders
class Order(models.Model):
    PENDING, CONFIRMED, PACKED, SHIPPED, DELIVERED, CANCELLED = (
        "pending", "confirmed", "packed", "shipped", "delivered", "cancelled")
    STATUS = [
        (PENDING, "Awaiting payment"), (CONFIRMED, "Confirmed"), (PACKED, "Packed"),
        (SHIPPED, "Shipped"), (DELIVERED, "Delivered"), (CANCELLED, "Cancelled"),
    ]
    PAY_PENDING, PAID, PAY_FAILED, REFUNDED = "pending", "paid", "failed", "refunded"
    PAY_STATUS = [(PAY_PENDING, "Pending"), (PAID, "Paid"), (PAY_FAILED, "Failed"), (REFUNDED, "Refunded")]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="orders")
    status = models.CharField(max_length=12, choices=STATUS, default=PENDING)
    payment_status = models.CharField(max_length=10, choices=PAY_STATUS, default=PAY_PENDING)

    ship_name = models.CharField(max_length=100)
    ship_phone = models.CharField(max_length=20)
    ship_line1 = models.CharField(max_length=200)
    ship_line2 = models.CharField(max_length=200, blank=True)
    ship_city = models.CharField(max_length=80)
    ship_state = models.CharField(max_length=80)
    ship_pincode = models.CharField(max_length=10)

    subtotal = models.DecimalField("Items at MRP", max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)

    razorpay_order_id = models.CharField(max_length=60, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=60, blank=True)
    razorpay_signature = models.CharField(max_length=200, blank=True)
    payment_error = models.CharField(max_length=300, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = "ROSA" + uuid.uuid4().hex[:10].upper()
        super().save(*args, **kwargs)

    @property
    def amount_paise(self):
        return int((self.total * Decimal(100)).quantize(Decimal("1")))

    @property
    def ship_address(self):
        parts = [self.ship_line1, self.ship_line2, self.ship_city, self.ship_state, self.ship_pincode]
        return ", ".join(p for p in parts if p)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    product_name = models.CharField(max_length=200)
    image_url = models.CharField(max_length=300, blank=True)
    size = models.CharField(max_length=20, blank=True)
    colour = models.CharField(max_length=40, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class PaymentEvent(models.Model):
    """Razorpay webhook event ids already handled (prevents duplicate processing)."""
    event_id = models.CharField(max_length=80, unique=True)
    event_type = models.CharField(max_length=60, blank=True)
    received_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.event_type} {self.event_id}"
