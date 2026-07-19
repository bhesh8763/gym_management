from rest_framework import serializers
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    collected_by_name = serializers.CharField(source='collected_by.get_full_name', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'member', 'member_name', 'membership', 'payment_for',
            'amount', 'discount', 'amount_paid', 'payment_method', 'status',
            'transaction_id', 'receipt_number', 'paid_at',
            'collected_by', 'collected_by_name', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'amount_paid', 'collected_by', 'created_at', 'updated_at']