from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "ROSA"

urlpatterns = [
    path("", views.home, name="home"),
    path("shop/", views.product_list, name="product_list"),
    path("shop/<slug:category_slug>/", views.product_list, name="product_list_category"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),

    path("bag/", views.cart_view, name="cart"),
    path("bag/add/", views.cart_add, name="cart_add"),
    path("bag/update/", views.cart_update, name="cart_update"),
    path("bag/remove/", views.cart_remove, name="cart_remove"),

    path("wishlist/", views.wishlist_view, name="wishlist"),
    path("wishlist/toggle/", views.wishlist_toggle, name="wishlist_toggle"),

    path("account/login/", views.RosaLoginView.as_view(), name="login"),
    path("account/logout/", LogoutView.as_view(), name="logout"),
    path("account/register/", views.register, name="register"),
    path("account/profile/", views.profile, name="profile"),
    path("account/address/<int:pk>/delete/", views.address_delete, name="address_delete"),
    path("account/orders/", views.order_history, name="order_history"),

    path("checkout/", views.checkout, name="checkout"),
    path("checkout/create-order/", views.create_order, name="create_order"),
    path("payment/verify/", views.payment_verify, name="payment_verify"),
    path("payment/failed-report/", views.payment_failed_report, name="payment_failed_report"),
    path("payment/success/<str:order_number>/", views.payment_success, name="payment_success"),
    path("payment/failed/<str:order_number>/", views.payment_failed, name="payment_failed"),
    path("webhooks/razorpay/", views.razorpay_webhook, name="razorpay_webhook"),

    path("ai/chat/", views.ai_chat, name="ai_chat"),
    path("ai/compare/", views.ai_compare, name="ai_compare"),

    path("subscribe/", views.subscribe, name="subscribe"),
    path("page/<slug:page>/", views.static_page, name="page"),
]
