"""Cart helpers. All money maths happens here on the server."""
from decimal import Decimal

from django.conf import settings

from .models import CartItem


def _owner_filter(request):
    if request.user.is_authenticated:
        return {"user": request.user}
    if not request.session.session_key:
        request.session.create()
    return {"user": None, "session_key": request.session.session_key}


def get_cart_items(request):
    if not request.user.is_authenticated and not request.session.session_key:
        return []
    return list(
        CartItem.objects.filter(**_owner_filter(request))
        .select_related("product", "size", "colour")
        .prefetch_related("product__images")
    )


def find_item(request, product, size, colour):
    return CartItem.objects.filter(
        product=product, size=size, colour=colour, **_owner_filter(request)
    ).first()


def create_item(request, product, size, colour, quantity):
    filt = _owner_filter(request)
    return CartItem.objects.create(
        product=product, size=size, colour=colour, quantity=quantity,
        user=filt.get("user"), session_key=filt.get("session_key", ""),
    )


def item_for_request(request, item_id):
    return CartItem.objects.filter(pk=item_id, **_owner_filter(request)).select_related("product").first()


def summarize(items):
    """Return subtotal (MRP), discount, delivery and total as Decimals."""
    mrp = sum((i.line_mrp for i in items), Decimal("0"))
    sale = sum((i.line_total for i in items), Decimal("0"))
    delivery = Decimal("0")
    if items and sale < Decimal(settings.ROSA_FREE_DELIVERY_ABOVE):
        delivery = Decimal(settings.ROSA_DELIVERY_CHARGE)
    return {
        "count": sum(i.quantity for i in items),
        "subtotal": mrp,
        "discount": mrp - sale,
        "items_total": sale,
        "delivery": delivery,
        "total": sale + delivery,
        "free_delivery_gap": max(Decimal("0"), Decimal(settings.ROSA_FREE_DELIVERY_ABOVE) - sale) if items else Decimal("0"),
    }


def merge_session_cart(user, session_key):
    """Move an anonymous cart into the user's cart after login/registration."""
    if not session_key:
        return
    for item in CartItem.objects.filter(user=None, session_key=session_key):
        existing = CartItem.objects.filter(user=user, product=item.product, size=item.size, colour=item.colour).first()
        if existing:
            existing.quantity = min(existing.quantity + item.quantity, max(item.product.stock, 1))
            existing.save(update_fields=["quantity"])
            item.delete()
        else:
            item.user = user
            item.session_key = ""
            item.save(update_fields=["user", "session_key"])
