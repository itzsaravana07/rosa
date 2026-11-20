from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html

from . import ai
from .models import (Address, CartItem, Category, Colour, Order, OrderItem, PaymentEvent, Product,
                     ProductImage, Profile, Promotion, Size, Subscriber, WishlistItem)

User = get_user_model()


def thumb(image, size=48):
    if not image:
        return "–"
    return format_html('<img src="{}" style="height:{}px;width:{}px;object-fit:cover;border-radius:6px">',
                       image.url, size, int(size * 0.8))


# ------------------------------------------------------------------ catalogue
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "show_in_nav", "is_active", "order")
    list_editable = ("show_in_nav", "is_active", "order")
    list_filter = ("parent", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)


@admin.register(Colour)
class ColourAdmin(admin.ModelAdmin):
    list_display = ("name", "swatch", "hex_code")

    @admin.display(description="Swatch")
    def swatch(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:50%;'
                           'background:{};border:1px solid #ccc"></span>', obj.hex_code)


class ProductImageFormSet(BaseInlineFormSet):
    """Pre-label the five empty slots: front, back, side, close-up, lifestyle."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial = [{"label": key} for key, _ in ProductImage.LABELS]


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    formset = ProductImageFormSet
    extra = 5
    fields = ("image", "preview", "label", "order")
    readonly_fields = ("preview",)

    @admin.display(description="Preview")
    def preview(self, obj):
        return thumb(obj.image, 60) if obj.pk else "–"


@admin.action(description="Mark selected as featured (Trending)")
def make_featured(modeladmin, request, queryset):
    queryset.update(is_featured=True)


@admin.action(description="Remove from featured")
def remove_featured(modeladmin, request, queryset):
    queryset.update(is_featured=False)


@admin.action(description="Mark selected as new arrivals")
def make_new(modeladmin, request, queryset):
    queryset.update(is_new_arrival=True)


@admin.action(description="Write AI description (only for products with an empty description)")
def ai_describe(modeladmin, request, queryset):
    done = 0
    for product in queryset.filter(description=""):
        try:
            product.description = ai.generate_product_description(product)
            product.save(update_fields=["description"])
            done += 1
        except ai.AIUnavailable as exc:
            modeladmin.message_user(request, str(exc), messages.ERROR)
            return
    modeladmin.message_user(request, f"Wrote descriptions for {done} product(s). Review them before publishing.")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "name", "brand", "category", "price", "discount_price", "stock",
                    "is_featured", "is_new_arrival", "is_active")
    list_editable = ("price", "discount_price", "stock", "is_featured", "is_new_arrival", "is_active")
    list_filter = ("category", "is_featured", "is_new_arrival", "is_active", "brand")
    search_fields = ("name", "brand", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("sizes", "colours")
    inlines = [ProductImageInline]
    actions = [make_featured, remove_featured, make_new, ai_describe]
    list_per_page = 25
    fieldsets = (
        ("Basics", {"fields": ("name", "slug", "brand", "category", "description")}),
        ("Pricing & stock", {"fields": ("price", "discount_price", "stock")}),
        ("Variants", {"fields": ("sizes", "colours")}),
        ("Visibility", {"fields": ("is_active", "is_featured", "is_new_arrival")}),
    )

    @admin.display(description="Image")
    def thumbnail(self, obj):
        img = obj.images.first()
        return thumb(img.image if img else None)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "title", "placement", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("placement", "is_active")

    @admin.display(description="Image")
    def thumbnail(self, obj):
        return thumb(obj.image)


# ------------------------------------------------------------------ customers
class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0

admin.site.unregister(User)
@admin.register(User)
class CustomerAdmin(BaseUserAdmin):
    inlines = [ProfileInline, AddressInline]
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name", "profile__phone")


@admin.register(WishlistItem)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "added_at")
    search_fields = ("user__username", "product__name")


# ------------------------------------------------------------------ orders
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "size", "colour", "unit_price", "quantity")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.action(description="Mark as shipped")
def mark_shipped(modeladmin, request, queryset):
    queryset.filter(payment_status=Order.PAID).update(status=Order.SHIPPED)


@admin.action(description="Mark as delivered")
def mark_delivered(modeladmin, request, queryset):
    queryset.filter(payment_status=Order.PAID).update(status=Order.DELIVERED)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "user", "total", "payment_status", "status", "created_at")
    list_editable = ("status",)
    list_filter = ("status", "payment_status", "created_at")
    search_fields = ("order_number", "user__username", "user__email", "ship_name", "razorpay_payment_id")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline]
    actions = [mark_shipped, mark_delivered]
    readonly_fields = ("order_number", "user", "subtotal", "discount", "delivery_charge", "total",
                       "payment_status", "razorpay_order_id", "razorpay_payment_id", "razorpay_signature",
                       "payment_error", "paid_at", "created_at")
    fieldsets = (
        ("Order", {"fields": ("order_number", "user", "status", "created_at")}),
        ("Shipping address", {"fields": ("ship_name", "ship_phone", "ship_line1", "ship_line2",
                                         "ship_city", "ship_state", "ship_pincode")}),
        ("Amounts", {"fields": ("subtotal", "discount", "delivery_charge", "total")}),
        ("Payment", {"fields": ("payment_status", "razorpay_order_id", "razorpay_payment_id",
                                "razorpay_signature", "payment_error", "paid_at")}),
    )

    def has_add_permission(self, request):
        return False


admin.site.register(Subscriber)
admin.site.register(PaymentEvent)
admin.site.register(CartItem)
