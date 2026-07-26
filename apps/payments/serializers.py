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

    def validate(self, data):
        # amount_paid = amount - discount is computed in Payment.save(); a
        # discount larger than the amount would silently make that negative.
        amount = data.get('amount', getattr(self.instance, 'amount', None))
        discount = data.get('discount', getattr(self.instance, 'discount', 0))
        if amount is not None and discount is not None and discount > amount:
            raise serializers.ValidationError(
                {'discount': 'Discount cannot be greater than the payment amount.'}
            )
        return data