# subscriptions/serializers.py
from rest_framework import serializers
from .models import SubscriptionPlan, Subscription, Payment


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Serializer for subscription plans"""
    
    # Convert features dict to list for frontend
    features = serializers.SerializerMethodField()
    
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'description', 'plan_type',
            'monthly_price', 'yearly_price',
            'ai_enabled', 'max_users', 'max_documents', 'max_ai_queries',
            'features', 'is_active', 'recommended'
        ]
    
    def get_features(self, obj):
        """Convert features dict to list of strings"""
        if not obj.features:
            return []
        
        features_list = []
        
        # Common feature mappings
        if obj.max_users:
            if obj.max_users >= 9999:
                features_list.append('Unlimited team members')
            else:
                features_list.append(f'Up to {obj.max_users} team members')
        
        if obj.max_ai_queries:
            features_list.append(f'{obj.max_ai_queries:,} AI conversations/month')
        
        if obj.max_documents:
            if obj.max_documents >= 9999:
                features_list.append('Unlimited document upload')
            else:
                features_list.append(f'Document upload ({obj.max_documents} docs)')
        
        # Add features from JSON
        for key, value in obj.features.items():
            if isinstance(value, bool) and value:
                features_list.append(key.replace('_', ' ').title())
            elif isinstance(value, str):
                features_list.append(value)
        
        return features_list


class SubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for subscriptions"""
    
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_id = serializers.CharField(source='plan.id', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'tenant_name', 'plan_id', 'plan_name',
            'status', 'billing_cycle',
            'start_date', 'end_date', 'next_billing_date',
            'amount_paid', 'is_active', 'auto_renew',
            'created_at'
        ]


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for payments"""
    
    class Meta:
        model = Payment
        fields = [
            'id', 'razorpay_order_id', 'razorpay_payment_id',
            'amount', 'currency', 'status', 'payment_method',
            'billing_cycle', 'plan_name', 'created_at'
        ]