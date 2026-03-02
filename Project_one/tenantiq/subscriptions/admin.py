# subscriptions/admin.py
from django.contrib import admin
from .models import SubscriptionPlan, Subscription, Payment, WebhookLog


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = [
        'name', 
        'plan_type', 
        'monthly_price', 
        'yearly_price',
        'max_users', 
        'is_active', 
        'recommended'
    ]
    list_filter = ['plan_type', 'is_active', 'recommended']
    search_fields = ['name', 'description']
    ordering = ['monthly_price']  # Changed from 'price' to 'monthly_price'
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'description', 'plan_type', 'is_active', 'recommended')
        }),
        ('Pricing', {
            'fields': ('monthly_price', 'yearly_price')
        }),
        ('Limits', {
            'fields': ('max_users', 'max_documents', 'max_ai_queries', 'ai_enabled')
        }),
        ('Features', {
            'fields': ('features',)
        }),
        ('Razorpay Integration', {
            'fields': ('razorpay_monthly_plan_id', 'razorpay_yearly_plan_id'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        'tenant',
        'plan',
        'status',
        'billing_cycle',
        'start_date',
        'end_date',
        'is_active',
        'auto_renew'
    ]
    list_filter = ['status', 'billing_cycle', 'is_active', 'auto_renew']
    search_fields = ['tenant__name', 'plan__name', 'razorpay_subscription_id']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Subscription Info', {
            'fields': ('tenant', 'plan', 'status', 'billing_cycle')
        }),
        ('Dates', {
            'fields': ('start_date', 'end_date', 'next_billing_date', 'cancelled_at')
        }),
        ('Razorpay Details', {
            'fields': ('razorpay_subscription_id', 'razorpay_customer_id'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': ('is_active', 'auto_renew', 'payment_method', 'amount_paid')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'razorpay_order_id',
        'subscription',
        'amount',
        'currency',
        'status',
        'payment_method',
        'created_at'
    ]
    list_filter = ['status', 'currency', 'billing_cycle']
    search_fields = [
        'razorpay_order_id',
        'razorpay_payment_id',
        'subscription__tenant__name'
    ]
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Payment Info', {
            'fields': ('subscription', 'amount', 'currency', 'status', 'payment_method')
        }),
        ('Razorpay Details', {
            'fields': (
                'razorpay_order_id',
                'razorpay_payment_id',
                'razorpay_signature'
            )
        }),
        ('Metadata', {
            'fields': ('billing_cycle', 'plan_name')
        }),
        ('Error Details', {
            'fields': ('error_code', 'error_description'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = [
        'event_type',
        'processed',
        'success',
        'created_at'
    ]
    list_filter = ['event_type', 'processed', 'success']
    search_fields = ['event_type', 'payload']
    ordering = ['-created_at']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Webhook Info', {
            'fields': ('event_type', 'processed', 'success')
        }),
        ('Payload', {
            'fields': ('payload',)
        }),
        ('Error', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Timestamp', {
            'fields': ('created_at',)
        }),
    )