from django.conf import settings

from .cart import get_cart_items
from .models import Category, WishlistItem


def store(request):
    roots = (Category.objects.filter(parent__isnull=True, is_active=True)
             .prefetch_related("children").order_by("order", "name"))
    items = get_cart_items(request) if hasattr(request, "session") else []
    wishlist_ids = set()
    if request.user.is_authenticated:
        wishlist_ids = set(WishlistItem.objects.filter(user=request.user).values_list("product_id", flat=True))
    return {
        "STORE_NAME": settings.STORE_NAME,
        "STORE_PHONE": settings.STORE_PHONE,
        "STORE_EMAIL": settings.STORE_EMAIL,
        "nav_categories": roots,
        "cart_count": sum(i.quantity for i in items),
        "wishlist_ids": wishlist_ids,
        "wishlist_count": len(wishlist_ids),
    }
