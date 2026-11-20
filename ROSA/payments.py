"""Razorpay helpers. Secrets stay on the server."""
import logging

import razorpay
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CartItem, Order, Product

log = logging.getLogger(__name__)


def client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_razorpay_order(order: Order) -> dict:
    return client().order.create({
        "amount": order.amount_paise,       # always computed on the server
        "currency": "INR",
        "receipt": order.order_number,
        "notes": {"order_number": order.order_number},
    })


def verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """Raises razorpay.errors.SignatureVerificationError when invalid."""
    client().utility.verify_payment_signature({
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
    })


def verify_webhook_signature(body: str, signature: str):
    client().utility.verify_webhook_signature(body, signature, settings.RAZORPAY_WEBHOOK_SECRET)


def finalize_paid(razorpay_order_id, payment_id, signature=""):
    """Mark an order paid exactly once. Safe to call from verify AND webhook.

    Returns (order, newly_paid). newly_paid is False when it was already processed.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(razorpay_order_id=razorpay_order_id).first()
        if order is None:
            return None, False
        if order.payment_status == Order.PAID:
            return order, False
        order.payment_status = Order.PAID
        order.status = Order.CONFIRMED
        order.razorpay_payment_id = payment_id or order.razorpay_payment_id
        if signature:
            order.razorpay_signature = signature
        order.payment_error = ""
        order.paid_at = timezone.now()
        order.save()
        for item in order.items.all():
            if item.product_id:
                product = Product.objects.select_for_update().get(pk=item.product_id)
                product.stock = max(0, product.stock - item.quantity)
                product.save(update_fields=["stock"])
        if order.user_id:
            CartItem.objects.filter(user_id=order.user_id).delete()
    return order, True


def mark_failed(order: Order, reason: str = ""):
    """Record a failed attempt, but never overwrite a paid order."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.payment_status == Order.PAID:
            return order
        order.payment_status = Order.PAY_FAILED
        order.payment_error = (reason or "Payment failed")[:300]
        order.save(update_fields=["payment_status", "payment_error"])
    return order
