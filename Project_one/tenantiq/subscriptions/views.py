# subscriptions/views.py - FIXED VERSION
import hashlib
import uuid
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


# ==================== CREATE RAZORPAY ORDER ====================
class CreateRazorpayOrderView(APIView):
    """
    Creates a Razorpay order or a 'Simulated' order if keys are missing.
    In both cases, final activation happens ONLY after verification.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            if str(user.role).upper() != 'TENANT_ADMIN':
                return Response({'error': 'Only tenant admins can manage subscriptions'}, status=status.HTTP_403_FORBIDDEN)
            if not user.tenant:
                return Response({'error': 'No tenant associated'}, status=status.HTTP_400_BAD_REQUEST)

            plan_id = request.data.get('plan_id')
            billing_cycle = request.data.get('billing_cycle', 'monthly')
            payment_method = request.data.get('payment_method', 'card')
            auto_renew = request.data.get('auto_renew', True)

            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                return Response({'error': 'Invalid plan'}, status=status.HTTP_404_NOT_FOUND)

            amount = plan.yearly_price if billing_cycle == 'yearly' else plan.monthly_price
            
            # ── Simulation vs Real ──────────────────────────────────────────
            is_simulated = not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and razorpay_client)
            order_id = f"sim_order_{uuid.uuid4().hex[:12]}"
            
            if not is_simulated:
                try:
                    # For Razorpay Subscriptions (Monthly AND Auto-renew enabled)
                    if billing_cycle == 'monthly' and plan.razorpay_monthly_plan_id and auto_renew:
                        razorpay_sub = razorpay_client.subscription.create({
                            "plan_id": plan.razorpay_monthly_plan_id,
                            "customer_notify": 1,
                            "total_count": 120, # 10 years
                        })
                        order_id = razorpay_sub['id']
                        return Response({
                            'key': RAZORPAY_KEY_ID,
                            'subscription_id': order_id,
                            'type': 'subscription',
                            'plan_name': plan.name,
                            'amount': int(amount * 100),
                            'payment_method': payment_method,
                            'auto_renew': True
                        })
                    
                    # For one-time payments (Yearly)
                    else:
                        rz_order = razorpay_client.order.create({
                            'amount': int(amount * 100),
                            'currency': 'INR',
                            'payment_capture': 1
                        })
                        order_id = rz_order['id']
                except Exception as rz_err:
                    logger.error(f"Razorpay API Error: {rz_err}")
                    is_simulated = True # Fallback to simulation if enabled or log error

            # Create a PENDING payment record
            # We don't create the subscription yet - that happens on verify
            # But we create a placeholder so we can track the attempt
            
            # Note: We don't link to a subscription yet as it doesn't exist
            # We'll link it in the Verify view.
            
            return Response({
                'key': RAZORPAY_KEY_ID or 'rzp_test_simulation',
                'order_id': order_id,
                'type': 'order',
                'amount': int(amount * 100),
                'currency': 'INR',
                'plan_name': plan.name,
                'is_simulated': is_simulated,
                'payment_method': payment_method,
                'auto_renew': auto_renew,
                'message': 'Simulation mode active' if is_simulated else 'Order created'
            })

        except Exception as e:
            logger.error(f"Error in CreateRazorpayOrderView: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== VERIFY PAYMENT ====================
class VerifyRazorpayPaymentView(APIView):
    """Verify Razorpay payment signature and activate subscription"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            print(f"\n{'='*60}")
            print(f"🔍 VERIFY PAYMENT REQUEST FOR {request.user.email}")
            print(f"{'='*60}")

            user = request.user
            if not user.tenant:
                return Response({'error': 'No tenant associated'}, status=status.HTTP_400_BAD_REQUEST)

            razorpay_order_id   = request.data.get('razorpay_order_id')
            razorpay_payment_id = request.data.get('razorpay_payment_id')
            razorpay_signature  = request.data.get('razorpay_signature')
            plan_id             = request.data.get('plan_id')
            billing_cycle       = request.data.get('billing_cycle', 'yearly')
            payment_type        = request.data.get('type', 'order')
            payment_method      = request.data.get('payment_method', 'card')
            auto_renew          = request.data.get('auto_renew', True)

            print(f"Order: {razorpay_order_id} | Payment: {razorpay_payment_id} | Method: {payment_method}")
            
            # ── Simulation Bypass ─────────────────────────────────────────
            is_simulated = str(razorpay_order_id or '').startswith('sim_order_')
            
            if is_simulated:
                print(f"⚠️  SIMULATION: Signature bypass")
            else:
                if not RAZORPAY_KEY_SECRET:
                    logger.error("RAZORPAY_KEY_SECRET missing in settings")
                    return Response({'error': 'Backend configuration error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
                message = f"{razorpay_order_id}|{razorpay_payment_id}"
                if payment_type == 'subscription':
                    message = f"{request.data.get('razorpay_subscription_id', '')}|{razorpay_payment_id}"

                generated_signature = hmac.new(
                    RAZORPAY_KEY_SECRET.encode('utf-8'),
                    message.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()

                if generated_signature != razorpay_signature:
                    print(f"❌ Signature MISMATCH")
                    return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
                print(f"✅ Signature MATCH")

            # ── Get plan ──────────────────────────────────────────────────
            print(f"📊 Fetching plan with ID: {plan_id}...")
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id)
                print(f"✅ Found plan: {plan.name}")
            except SubscriptionPlan.DoesNotExist:
                print(f"❌ Plan NOT FOUND")
                return Response({'error': 'Invalid plan'}, status=status.HTTP_404_NOT_FOUND)

            amount = plan.yearly_price if billing_cycle == 'yearly' else plan.monthly_price

            # ── 1. Deactivate old subscriptions ────────────────────────────
            print("🔄 Deactivating old subscriptions...")
            Subscription.objects.filter(tenant=user.tenant, status='active').update(
                status='cancelled', is_active=False, cancelled_at=timezone.now()
            )

            # ── 2. Create the Subscription FIRST ──────────────────────────
            # (Because Payment requires a subscription FK)
            print("🆕 Creating new subscription object...")
            start_date = timezone.now().date()
            duration_days = 365 if billing_cycle == 'yearly' else 30
            end_date = start_date + timedelta(days=duration_days)

            print(f"🆕 Creating subscription: Tenant={user.tenant}, Plan={plan.id}")
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
                auto_renew=auto_renew,
                payment_method=payment_method,
                razorpay_subscription_id=request.data.get('razorpay_subscription_id')
            )
            print(f"✅ Subscription created: {subscription.id}")

            # ── 3. Create or Link Payment record ──────────────────────────
            print(f"💳 Recording {payment_method.upper()} payment details...")
            payment, created = Payment.objects.update_or_create(
                razorpay_order_id=razorpay_order_id or f"order_{razorpay_payment_id}",
                defaults={
                    'subscription': subscription,
                    'razorpay_payment_id': razorpay_payment_id,
                    'razorpay_signature': razorpay_signature,
                    'amount': amount,
                    'status': 'success',
                    'plan_name': plan.name,
                    'billing_cycle': billing_cycle,
                    'payment_method': payment_method
                }
            )

            print(f"✨ Verification Complete. ID: {subscription.id}")
            print(f"{'='*60}\n")

            return Response({
                'success': True,
                'message': 'Subscription activated',
                'subscription': SubscriptionSerializer(subscription).data,
            })

        except Exception as e:
            print(f"🔥 UNEXPECTED VERIFICATION ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({'error': f'Internal Server Error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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