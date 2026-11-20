import json
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from razorpay.errors import SignatureVerificationError

from . import ai, cart as cartlib, payments
from .forms import AddressForm, ProfileForm, RegisterForm, UserForm
from .models import (Address, CartItem, Category, Colour, Order, OrderItem, PaymentEvent, Product,
                     Promotion, Size, Subscriber, WishlistItem)

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ helpers
def product_qs():
    return (Product.objects.filter(is_active=True)
            .select_related("category", "category__parent")
            .prefetch_related("images", "sizes", "colours"))


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _int(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _fail(request, message, status=400, fallback="ROSA:cart"):
    if _is_ajax(request):
        return JsonResponse({"ok": False, "message": message}, status=status)
    messages.error(request, message)
    return redirect(request.META.get("HTTP_REFERER") or reverse(fallback))


# ------------------------------------------------------------------ home & catalogue
def home(request):
    promos = Promotion.objects.filter(is_active=True)
    trending = list(product_qs().filter(is_featured=True)[:12]) or list(product_qs()[:12])
    return render(request, "ROSA/home.html", {
        "hero": promos.filter(placement=Promotion.HERO).first(),
        "hero_secondary": promos.filter(placement=Promotion.HERO_SECONDARY).first(),
        "promo_cards": promos.filter(placement=Promotion.CARD)[:3],
        "banner": promos.filter(placement=Promotion.BANNER).first(),
        "trending": trending,
        "new_arrivals": product_qs().filter(is_new_arrival=True)[:8],
    })


def product_list(request, category_slug=None):
    qs = product_qs().annotate(effective=Coalesce("discount_price", "price"))
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug, is_active=True)
        qs = qs.filter(Q(category=category) | Q(category__parent=category))

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(brand__icontains=q) | Q(description__icontains=q)
                       | Q(category__name__icontains=q) | Q(category__parent__name__icontains=q))
    if request.GET.get("new"):
        qs = qs.filter(is_new_arrival=True)
    if request.GET.get("featured"):
        qs = qs.filter(is_featured=True)
    if request.GET.get("sale"):
        qs = qs.filter(discount_price__isnull=False, discount_price__lt=F("price"))
    size = request.GET.get("size")
    if size and size.isdigit():
        qs = qs.filter(sizes__id=size)
    colour = request.GET.get("colour")
    if colour and colour.isdigit():
        qs = qs.filter(colours__id=colour)
    lo, hi = _dec(request.GET.get("min")), _dec(request.GET.get("max"))
    if lo is not None:
        qs = qs.filter(effective__gte=lo)
    if hi is not None:
        qs = qs.filter(effective__lte=hi)

    sort = request.GET.get("sort", "new")
    qs = qs.order_by({"price_asc": "effective", "price_desc": "-effective", "name": "name"}.get(sort, "-created_at")).distinct()

    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "ROSA/product_list.html", {
        "page": page, "category": category, "q": q, "sort": sort,
        "sizes": Size.objects.all(), "colours": Colour.objects.all(),
        "selected_size": size, "selected_colour": colour,
        "min": request.GET.get("min", ""), "max": request.GET.get("max", ""),
        "querystring": params.urlencode(),
        "total": page.paginator.count,
    })


def product_detail(request, slug):
    product = get_object_or_404(product_qs(), slug=slug)
    related = (product_qs().filter(category=product.category).exclude(pk=product.pk))[:4]
    return render(request, "ROSA/product_detail.html", {
        "product": product,
        "images": list(product.images.all()),
        "related": related,
    })


STATIC_PAGES = {
    "about": ("About ROSA", "ROSA is a fashion and lifestyle label built around everyday pieces made well. We design for the way people actually dress, and we keep the range small enough to stay good."),
    "support": ("Customer support", "Questions about an order, a size or a return? Write to us at the email in the footer or call during store hours, Monday to Saturday, 10 am to 7 pm IST."),
    "shipping": ("Shipping and returns", "Orders ship within 2 business days. Delivery is free above ₹1,999, otherwise ₹99. Unworn items can be returned within 7 days of delivery."),
    "privacy": ("Privacy policy", "We collect only what we need to process your order and improve the store. We never sell personal data. Payments are handled by Razorpay; we do not store card details."),
    "terms": ("Terms and conditions", "By placing an order you agree to our pricing, shipping and returns policies. Prices are in Indian rupees and include applicable taxes unless stated."),
    "contact": ("Contact us", "We read every message. Reach the team using the phone number and email in the header and footer."),
    "store": ("Store information", "Visit us during store hours, Monday to Saturday, 10 am to 7 pm IST. Add your store address here from the admin or the page template."),
}


def static_page(request, page):
    if page not in STATIC_PAGES:
        raise Http404
    title, body = STATIC_PAGES[page]
    return render(request, "ROSA/page.html", {"title": title, "body": body})


@require_POST
def subscribe(request):
    email = request.POST.get("email", "").strip().lower()
    if "@" not in email or len(email) > 254:
        return _fail(request, "Enter a valid email address.", fallback="ROSA:home")
    _, created = Subscriber.objects.get_or_create(email=email)
    msg = "You're on the list. Welcome to ROSA." if created else "That email is already subscribed."
    if _is_ajax(request):
        return JsonResponse({"ok": True, "message": msg})
    messages.success(request, msg)
    return redirect(request.META.get("HTTP_REFERER") or "ROSA:home")


# ------------------------------------------------------------------ cart
def cart_view(request):
    items = cartlib.get_cart_items(request)
    return render(request, "ROSA/cart.html", {"items": items, "summary": cartlib.summarize(items)})


@require_POST
def cart_add(request):
    product = get_object_or_404(Product, pk=_int(request.POST.get("product_id"), 0), is_active=True)
    qty = max(1, _int(request.POST.get("quantity"), 1))
    size = colour = None
    if product.sizes.exists():
        size = product.sizes.filter(pk=_int(request.POST.get("size"), 0)).first()
        if size is None:
            return _fail(request, "Please select a size.")
    if product.colours.exists():
        colour = product.colours.filter(pk=_int(request.POST.get("colour"), 0)).first()
        if colour is None:
            return _fail(request, "Please select a colour.")
    if not product.in_stock:
        return _fail(request, "Sorry, this item is out of stock.")

    existing = cartlib.find_item(request, product, size, colour)
    new_qty = (existing.quantity if existing else 0) + qty
    if new_qty > product.stock:
        return _fail(request, f"Only {product.stock} left in stock.")
    if existing:
        existing.quantity = new_qty
        existing.save(update_fields=["quantity"])
    else:
        cartlib.create_item(request, product, size, colour, qty)

    count = sum(i.quantity for i in cartlib.get_cart_items(request))
    if request.POST.get("buy_now"):
        return JsonResponse({"ok": True, "redirect": reverse("ROSA:checkout"), "count": count}) if _is_ajax(request) \
            else redirect("ROSA:checkout")
    if _is_ajax(request):
        return JsonResponse({"ok": True, "count": count, "message": f"{product.name} added to your bag."})
    messages.success(request, f"{product.name} added to your bag.")
    return redirect("ROSA:cart")


@require_POST
def cart_update(request):
    item = cartlib.item_for_request(request, _int(request.POST.get("item_id"), 0))
    if item is None:
        return _fail(request, "That item is no longer in your bag.")
    qty = _int(request.POST.get("quantity"), 1)
    if qty <= 0:
        item.delete()
    elif qty > item.product.stock:
        return _fail(request, f"Only {item.product.stock} left in stock.")
    else:
        item.quantity = qty
        item.save(update_fields=["quantity"])
    return redirect("ROSA:cart")


@require_POST
def cart_remove(request):
    item = cartlib.item_for_request(request, _int(request.POST.get("item_id"), 0))
    if item:
        item.delete()
        messages.success(request, "Item removed.")
    return redirect("ROSA:cart")


# ------------------------------------------------------------------ wishlist
@require_POST
def wishlist_toggle(request):
    if not request.user.is_authenticated:
        url = f"{reverse('ROSA:login')}?next={request.META.get('HTTP_REFERER', '/')}"
        if _is_ajax(request):
            return JsonResponse({"ok": False, "login_url": url, "message": "Log in to save items."}, status=401)
        return redirect(url)
    product = get_object_or_404(Product, pk=_int(request.POST.get("product_id"), 0), is_active=True)
    obj, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
    if not created:
        obj.delete()
    count = WishlistItem.objects.filter(user=request.user).count()
    if _is_ajax(request):
        return JsonResponse({"ok": True, "added": created, "count": count,
                             "message": "Saved to your wishlist." if created else "Removed from your wishlist."})
    return redirect(request.META.get("HTTP_REFERER") or "ROSA:wishlist")


@login_required
def wishlist_view(request):
    products = [w.product for w in WishlistItem.objects.filter(user=request.user)
                .select_related("product", "product__category", "product__category__parent")
                .prefetch_related("product__images", "product__sizes", "product__colours")]
    return render(request, "ROSA/wishlist.html", {"products": products})


# ------------------------------------------------------------------ accounts
class RosaLoginView(LoginView):
    template_name = "ROSA/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        old_key = self.request.session.session_key
        response = super().form_valid(form)
        cartlib.merge_session_cart(self.request.user, old_key)
        return response


def register(request):
    if request.user.is_authenticated:
        return redirect("ROSA:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        old_key = request.session.session_key
        user = form.save()
        login(request, user)
        cartlib.merge_session_cart(user, old_key)
        messages.success(request, f"Welcome to ROSA, {user.first_name}.")
        return redirect("ROSA:home")
    return render(request, "ROSA/register.html", {"form": form})


@login_required
def profile(request):
    user_form = UserForm(instance=request.user)
    profile_form = ProfileForm(instance=request.user.profile)
    address_form = AddressForm()
    kind = request.POST.get("form_type")
    if request.method == "POST" and kind == "profile":
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=request.user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Profile updated.")
            return redirect("ROSA:profile")
    elif request.method == "POST" and kind == "address":
        address_form = AddressForm(request.POST)
        if address_form.is_valid():
            addr = address_form.save(commit=False)
            addr.user = request.user
            if addr.is_default:
                request.user.addresses.update(is_default=False)
            addr.save()
            messages.success(request, "Address saved.")
            return redirect("ROSA:profile")
    return render(request, "ROSA/profile.html", {
        "user_form": user_form, "profile_form": profile_form, "address_form": address_form,
        "addresses": request.user.addresses.all(),
    })


@login_required
@require_POST
def address_delete(request, pk):
    get_object_or_404(Address, pk=pk, user=request.user).delete()
    messages.success(request, "Address removed.")
    return redirect(request.META.get("HTTP_REFERER") or "ROSA:profile")


@login_required
def order_history(request):
    orders = request.user.orders.prefetch_related("items").all()
    return render(request, "ROSA/order_history.html", {"orders": orders})


# ------------------------------------------------------------------ checkout & payments
@login_required
def checkout(request):
    items = cartlib.get_cart_items(request)
    if not items:
        messages.info(request, "Your bag is empty.")
        return redirect("ROSA:cart")
    problems = [i for i in items if i.quantity > i.product.stock or not i.product.is_active]
    if problems:
        messages.error(request, "Some items are no longer available in the quantity you chose. Update your bag to continue.")
        return redirect("ROSA:cart")
    return render(request, "ROSA/checkout.html", {
        "items": items, "summary": cartlib.summarize(items),
        "addresses": request.user.addresses.all(),
        "address_form": AddressForm(initial={"full_name": request.user.get_full_name(),
                                             "phone": request.user.profile.phone}),
    })


@login_required
@require_POST
def create_order(request):
    if not settings.RAZORPAY_CONFIGURED:
        return JsonResponse({"ok": False, "message": "Payments aren't switched on yet. Add your Razorpay keys to the .env file."}, status=503)

    items = cartlib.get_cart_items(request)
    if not items:
        return JsonResponse({"ok": False, "message": "Your bag is empty."}, status=400)
    for i in items:
        if not i.product.is_active or i.quantity > i.product.stock:
            return JsonResponse({"ok": False, "message": f"{i.product.name} is no longer available in that quantity."}, status=400)

    addr_id = request.POST.get("address_id", "new")
    if addr_id and addr_id != "new":
        address = get_object_or_404(Address, pk=_int(addr_id, 0), user=request.user)
    else:
        form = AddressForm(request.POST)
        if not form.is_valid():
            first = next(iter(form.errors.values()))[0]
            return JsonResponse({"ok": False, "message": first, "errors": form.errors}, status=400)
        address = form.save(commit=False)
        address.user = request.user
        if request.POST.get("save_address"):
            address.save()

    summary = cartlib.summarize(items)      # recalculated here, never taken from the browser
    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            ship_name=address.full_name, ship_phone=address.phone, ship_line1=address.line1,
            ship_line2=address.line2, ship_city=address.city, ship_state=address.state, ship_pincode=address.pincode,
            subtotal=summary["subtotal"], discount=summary["discount"],
            delivery_charge=summary["delivery"], total=summary["total"],
        )
        OrderItem.objects.bulk_create([
            OrderItem(order=order, product=i.product, product_name=i.product.name,
                      image_url=i.product.cover.image.url if i.product.cover else "",
                      size=i.size.name if i.size else "", colour=i.colour.name if i.colour else "",
                      unit_price=i.product.sale_price, quantity=i.quantity)
            for i in items
        ])
    try:
        rp = payments.create_razorpay_order(order)
    except Exception:
        log.exception("Razorpay order creation failed for %s", order.order_number)
        payments.mark_failed(order, "Could not create payment order")
        return JsonResponse({"ok": False, "message": "We couldn't start the payment. Please try again."}, status=502)

    order.razorpay_order_id = rp["id"]
    order.save(update_fields=["razorpay_order_id"])
    return JsonResponse({
        "ok": True,
        "key": settings.RAZORPAY_KEY_ID,
        "razorpay_order_id": rp["id"],
        "amount": order.amount_paise,
        "currency": "INR",
        "order_number": order.order_number,
        "store_name": settings.STORE_NAME,
        "prefill": {"name": address.full_name, "email": request.user.email, "contact": address.phone},
        "verify_url": reverse("ROSA:payment_verify"),
        "failed_url": reverse("ROSA:payment_failed_report"),
    })


@login_required
@require_POST
def payment_verify(request):
    data = request.POST
    rp_order, rp_payment, rp_sig = (data.get("razorpay_order_id", ""), data.get("razorpay_payment_id", ""),
                                    data.get("razorpay_signature", ""))
    order = Order.objects.filter(razorpay_order_id=rp_order, user=request.user).first()
    if order is None:
        return JsonResponse({"ok": False, "message": "Order not found."}, status=404)
    try:
        payments.verify_payment_signature(rp_order, rp_payment, rp_sig)
    except SignatureVerificationError:
        payments.mark_failed(order, "Signature verification failed")
        return JsonResponse({"ok": False, "message": "Payment could not be verified.",
                             "redirect": reverse("ROSA:payment_failed", args=[order.order_number])}, status=400)
    payments.finalize_paid(rp_order, rp_payment, rp_sig)
    return JsonResponse({"ok": True, "redirect": reverse("ROSA:payment_success", args=[order.order_number])})


@login_required
@require_POST
def payment_failed_report(request):
    order = Order.objects.filter(razorpay_order_id=request.POST.get("razorpay_order_id", ""), user=request.user).first()
    if order is None:
        return JsonResponse({"ok": False}, status=404)
    payments.mark_failed(order, request.POST.get("reason", "Payment failed"))
    return JsonResponse({"ok": True, "redirect": reverse("ROSA:payment_failed", args=[order.order_number])})


@login_required
def payment_success(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related("items"), order_number=order_number, user=request.user)
    if order.payment_status != Order.PAID:
        return redirect("ROSA:order_history")
    return render(request, "ROSA/payment_success.html", {"order": order})


@login_required
def payment_failed(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    return render(request, "ROSA/payment_failed.html", {"order": order})


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    secret_ok = bool(settings.RAZORPAY_WEBHOOK_SECRET) and "YOUR_" not in settings.RAZORPAY_WEBHOOK_SECRET
    if not (settings.RAZORPAY_CONFIGURED and secret_ok):
        return HttpResponse(status=503)
    body = request.body.decode("utf-8")
    try:
        payments.verify_webhook_signature(body, request.headers.get("X-Razorpay-Signature", ""))
    except SignatureVerificationError:
        return HttpResponse(status=400)

    event_id = request.headers.get("X-Razorpay-Event-Id", "")
    try:
        payload = json.loads(body)
    except ValueError:
        return HttpResponse(status=400)
    if event_id:
        _, created = PaymentEvent.objects.get_or_create(event_id=event_id, defaults={"event_type": payload.get("event", "")})
        if not created:
            return HttpResponse("duplicate", status=200)

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    rp_order, rp_payment = entity.get("order_id", ""), entity.get("id", "")
    if event in ("payment.captured", "order.paid") and rp_order:
        payments.finalize_paid(rp_order, rp_payment)
    elif event == "payment.failed" and rp_order:
        order = Order.objects.filter(razorpay_order_id=rp_order).first()
        if order:
            payments.mark_failed(order, entity.get("error_description", "Payment failed"))
    return HttpResponse("ok", status=200)


# ------------------------------------------------------------------ AI
def _rate_limited(request, bucket, limit=30, window=3600):
    ident = request.user.pk if request.user.is_authenticated else (request.META.get("REMOTE_ADDR") or "anon")
    key = f"ai:{bucket}:{ident}"
    n = cache.get(key, 0)
    if n >= limit:
        return True
    cache.set(key, n + 1, window)
    return False


def _card(p):
    cover = p.cover
    return {"name": p.name, "brand": p.brand, "url": p.get_absolute_url(), "price": f"₹{p.sale_price:,.0f}",
            "image": cover.image.url if cover else ""}


@require_POST
def ai_chat(request):
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)
    message = str(data.get("message", "")).strip()
    if not message:
        return JsonResponse({"ok": False, "message": "Type a question first."}, status=400)
    if _rate_limited(request, "chat"):
        return JsonResponse({"ok": False, "message": "You've reached the hourly limit. Try again later."}, status=429)
    try:
        reply, products = ai.shopping_assistant(message, data.get("history"), budget=_int(data.get("budget"), 0) or None)
    except ai.AIUnavailable as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=503)
    return JsonResponse({"ok": True, "reply": reply, "products": [_card(p) for p in products]})


@require_POST
def ai_compare(request):
    try:
        slugs = list(dict.fromkeys(json.loads(request.body or "{}").get("slugs", [])))[:3]
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)
    products = list(product_qs().filter(slug__in=slugs))
    if len(products) < 2:
        return JsonResponse({"ok": False, "message": "Pick at least two products to compare."}, status=400)
    if _rate_limited(request, "compare", limit=15):
        return JsonResponse({"ok": False, "message": "You've reached the hourly limit. Try again later."}, status=429)
    try:
        text = ai.compare_products(products)
    except ai.AIUnavailable as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=503)
    return JsonResponse({"ok": True, "reply": text})
