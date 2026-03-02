# subscriptions/views.py - FIXED VERSION
import hashlib
import hmac
import logging
import razorpay
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Payment, SubscriptionPlan, Subscription, WebhookLog
from .serializers import SubscriptionPlanSerializer, SubscriptionSerializer

logger = logging.getLogger('razorpay')

# ============ RAZORPAY INITIALIZATION ============
print("\n" + "="*60)
print("🔍 RAZORPAY INITIALIZATION")
print("="*60)

RAZORPAY_KEY_ID = getattr(settings, 'RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = (
    getattr(settings, 'RAZORPAY_KEY_SECRET', '')
    or getattr(settings, 'RAZORPAY_SECRET_KEY', '')
)

print(f"RAZORPAY_KEY_ID: {RAZORPAY_KEY_ID or 'NOT FOUND'}")
print(f"RAZORPAY_KEY_SECRET: {'SET (' + str(len(RAZORPAY_KEY_SECRET)) + ' chars)' if RAZORPAY_KEY_SECRET else 'NOT SET'}")

razorpay_client = None
try:
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        print(f"✅ Razorpay client initialized successfully")
        print(f"   Key ID: {RAZORPAY_KEY_ID[:12]}...")
    else:
        print(f"❌ Razorpay keys not configured — add to .env:")
        print(f"   RAZORPAY_KEY_ID=rzp_test_xxxxx")
        print(f"   RAZORPAY_KEY_SECRET=your_secret_key")
except Exception as e:
    print(f"❌ Failed to initialize Razorpay: {str(e)}")
    import traceback
    traceback.print_exc()

print("="*60 + "\n")


# ==================== SUBSCRIPTION PLANS ====================
class SubscriptionPlanListView(APIView):
    """Get all active subscription plans — public endpoint"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True).order_by('monthly_price')
        serializer = SubscriptionPlanSerializer(plans, many=True)
        return Response(serializer.data)


# ==================== CURRENT SUBSCRIPTION ====================
class CurrentSubscriptionView(APIView):
    """Get current active subscription for the logged-in user's tenant"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if str(user.role).upper() == 'SUPER_ADMIN':
            return Response({
                'has_subscription': True,
                'is_active': True,
                'is_super_admin': True,
            })

        if not user.tenant:
            return Response({
                'has_subscription': False,
                'is_active': False,
                'error': 'No tenant associated'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            subscription = Subscription.objects.get(
                tenant=user.tenant,
                status='active',
                is_active=True
            )
            serializer = SubscriptionSerializer(subscription)
            return Response({
                'has_subscription': True,
                'is_active': True,
                'subscription': serializer.data,
                **serializer.data
            })
        except Subscription.DoesNotExist:
            return Response({
                'has_subscription': False,
                'is_active': False,
            })


# ==================== CREATE RAZORPAY ORDER (DEV MODE) ====================
class CreateRazorpayOrderView(APIView):
    """
    DEV MODE: Auto-activates subscription without real payment.
    Replace with real Razorpay order creation before going to production.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            print(f"\n{'='*60}")
            print(f"📝 DEV MODE: CREATE ORDER (BYPASS)")
            print(f"{'='*60}")

            user = request.user

            if str(user.role).upper() != 'TENANT_ADMIN':
                return Response(
                    {'error': 'Only tenant admins can subscribe'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not user.tenant:
                return Response(
                    {'error': 'No tenant associated'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            plan_id = request.data.get('plan_id')
            billing_cycle = request.data.get('billing_cycle', 'monthly')

            if not plan_id:
                return Response(
                    {'error': 'plan_id is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                return Response(
                    {'error': 'Invalid or inactive plan'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # DEV MODE: Auto-activate subscription without payment
            print(f"⚠️  DEV MODE: Auto-activating subscription for {user.email}")

            # Cancel any existing active subscriptions
            Subscription.objects.filter(
                tenant=user.tenant,
                status='active'
            ).update(
                status='cancelled',
                is_active=False,
                cancelled_at=timezone.now()
            )

            # Create new subscription
            start_date = timezone.now().date()
            duration_days = 365 if billing_cycle == 'yearly' else 30
            end_date = start_date + timedelta(days=duration_days)
            amount = plan.yearly_price if billing_cycle == 'yearly' else plan.monthly_price

            subscription = Subscription.objects.create(
                tenant=user.tenant,
                plan=plan,
                status='active',
                billing_cycle=billing_cycle,
                start_date=start_date,
                end_date=end_date,
                next_billing_date=end_date,
                amount_paid=amount,
                is_active=True,
                auto_renew=False
            )

            # Create a dev payment record for audit trail
            Payment.objects.create(
                razorpay_order_id=f"dev_order_{subscription.id}",
                razorpay_payment_id=f"dev_payment_{subscription.id}",
                amount=amount,
                currency='INR',
                status='success',
                billing_cycle=billing_cycle,
                plan_name=plan.name,
                subscription=subscription
            )

            print(f"✅ DEV MODE: Subscription activated — ID {subscription.id}")
            print(f"{'='*60}\n")

            serializer = SubscriptionSerializer(subscription)
            return Response({
                'dev_mode': True,
                'success': True,
                'message': 'DEV MODE: Subscription activated without payment',
                'subscription': serializer.data,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            print(f"❌ Error in CreateRazorpayOrderView: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== VERIFY PAYMENT ====================
class VerifyRazorpayPaymentView(APIView):
    """Verify Razorpay payment signature and activate subscription"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            print(f"\n{'='*60}")
            print(f"🔍 VERIFY PAYMENT REQUEST")
            print(f"{'='*60}")

            user = request.user

            if not user.tenant:
                return Response(
                    {'error': 'No tenant associated'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            razorpay_order_id   = request.data.get('razorpay_order_id')
            razorpay_payment_id = request.data.get('razorpay_payment_id')
            razorpay_signature  = request.data.get('razorpay_signature')
            plan_id             = request.data.get('plan_id')
            billing_cycle       = request.data.get('billing_cycle', 'yearly')
            payment_type        = request.data.get('type', 'order')

            print(f"Order ID:   {razorpay_order_id}")
            print(f"Payment ID: {razorpay_payment_id}")
            print(f"Type:       {payment_type}")

            if not all([razorpay_payment_id, razorpay_signature, plan_id]):
                return Response(
                    {'error': 'Missing required fields'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ── Signature verification ────────────────────────────────────
            if payment_type == 'subscription':
                # Subscription flow: subscription_id|payment_id
                razorpay_subscription_id = request.data.get('razorpay_subscription_id', '')
                message = f"{razorpay_subscription_id}|{razorpay_payment_id}"
            else:
                # One-time order flow: order_id|payment_id
                message = f"{razorpay_order_id}|{razorpay_payment_id}"

            generated_signature = hmac.new(          # ← FIXED: was hmac.new (typo)
                RAZORPAY_KEY_SECRET.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            if generated_signature != razorpay_signature:
                print(f"❌ Signature verification failed")
                return Response(
                    {'error': 'Invalid payment signature'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            print(f"✅ Signature verified")

            # ── Get plan ──────────────────────────────────────────────────
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id)
            except SubscriptionPlan.DoesNotExist:
                return Response(
                    {'error': 'Invalid plan'},
                    status=status.HTTP_404_NOT_FOUND
                )

            amount = plan.yearly_price if billing_cycle == 'yearly' else plan.monthly_price

            # ── Upsert payment record ─────────────────────────────────────
            try:
                payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
                payment.razorpay_payment_id = razorpay_payment_id
                payment.razorpay_signature  = razorpay_signature
                payment.status = 'success'
                payment.save()
            except Payment.DoesNotExist:
                payment = Payment.objects.create(
                    razorpay_order_id=razorpay_order_id or f"order_{razorpay_payment_id}",
                    razorpay_payment_id=razorpay_payment_id,
                    razorpay_signature=razorpay_signature,
                    amount=amount,
                    currency='INR',
                    status='success',
                    billing_cycle=billing_cycle,
                    plan_name=plan.name,
                )

            # ── Cancel existing subscriptions ─────────────────────────────
            Subscription.objects.filter(
                tenant=user.tenant,
                status='active'
            ).update(
                status='cancelled',
                is_active=False,
                cancelled_at=timezone.now()
            )

            # ── Create new subscription ───────────────────────────────────
            start_date    = timezone.now().date()
            duration_days = 365 if billing_cycle == 'yearly' else 30
            end_date      = start_date + timedelta(days=duration_days)

            subscription = Subscription.objects.create(
                tenant=user.tenant,
                plan=plan,
                status='active',
                billing_cycle=billing_cycle,
                start_date=start_date,
                end_date=end_date,
                next_billing_date=end_date,
                amount_paid=payment.amount,
                is_active=True,
                auto_renew=(payment_type == 'subscription'),
            )

            payment.subscription = subscription
            payment.save()

            print(f"✅ Subscription activated for {user.email}")
            print(f"{'='*60}\n")

            serializer = SubscriptionSerializer(subscription)
            return Response({
                'success': True,
                'message': 'Payment verified and subscription activated',
                'subscription': serializer.data,
            })

        except Exception as e:
            print(f"❌ Verification error: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Verification failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== CANCEL SUBSCRIPTION ====================
class CancelSubscriptionView(APIView):
    """Cancel the active subscription for the current tenant"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user

            if str(user.role).upper() != 'TENANT_ADMIN':
                return Response(
                    {'error': 'Only tenant admins can cancel subscriptions'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not user.tenant:
                return Response(
                    {'error': 'No tenant associated'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                subscription = Subscription.objects.get(
                    tenant=user.tenant,
                    status='active',
                    is_active=True
                )
            except Subscription.DoesNotExist:
                return Response(
                    {'error': 'No active subscription found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            subscription.status     = 'cancelled'
            subscription.auto_renew = False
            subscription.cancelled_at = timezone.now()
            subscription.is_active  = False
            subscription.save()

            print(f"✅ Subscription cancelled for {user.email}")

            return Response({
                'success': True,
                'message': 'Subscription cancelled. Access continues until end of billing period.',
            })

        except Exception as e:
            print(f"❌ Error cancelling subscription: {str(e)}")
            return Response(
                {'error': f'Failed to cancel: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== WEBHOOK ====================
@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    """Handle Razorpay webhooks — no auth required"""
    permission_classes = []

    def post(self, request):
        try:
            webhook_signature = request.headers.get('X-Razorpay-Signature', '')
            webhook_body      = request.body.decode('utf-8')
            webhook_secret    = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')

            if webhook_secret:
                expected_signature = hmac.new(
                    webhook_secret.encode('utf-8'),
                    webhook_body.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()

                if webhook_signature != expected_signature:
                    return Response(
                        {'error': 'Invalid webhook signature'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            payload    = request.data
            event_type = payload.get('event', 'unknown')

            WebhookLog.objects.create(
                event_type=event_type,
                payload=payload,
                processed=True,
                success=True
            )

            print(f"✅ Webhook received: {event_type}")
            return Response({'status': 'success'})

        except Exception as e:
            print(f"❌ Webhook error: {str(e)}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )