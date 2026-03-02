# subscriptions/urls.py
from django.urls import path
from .views import (
    SubscriptionPlanListView,
    CurrentSubscriptionView,
    CreateRazorpayOrderView,
    VerifyRazorpayPaymentView,
    RazorpayWebhookView,
    CancelSubscriptionView,
)

app_name = 'subscriptions'

urlpatterns = [
    # Plans
    path('plans/', SubscriptionPlanListView.as_view(), name='plans-list'),

    # Current subscription status
    path('current/', CurrentSubscriptionView.as_view(), name='current-subscription'),

    # Razorpay payment flow
    path('razorpay/create-order/', CreateRazorpayOrderView.as_view(), name='create-order'),
    path('razorpay/verify/', VerifyRazorpayPaymentView.as_view(), name='verify-payment'),
    path('razorpay/webhook/', RazorpayWebhookView.as_view(), name='webhook'),

    # Subscription management
    path('cancel/', CancelSubscriptionView.as_view(), name='cancel-subscription'),
]