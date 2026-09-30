from rest_framework import serializers

from apps.gyms.tenancy import user_has_branch_access

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    collected_by_name = serializers.CharField(source='collected_by.get_full_name', read_only=True)
    due_remaining = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )

    class Meta:
        model = Payment
        fields = [
            'id', 'gym', 'branch', 'member', 'member_name', 'membership', 'payment_for',
            'amount', 'discount', 'amount_paid', 'due_remaining', 'payment_method', 'status',
            'transaction_id', 'receipt_number', 'paid_at',
            'collected_by', 'collected_by_name', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'amount_paid', 'due_remaining', 'collected_by', 'created_at', 'updated_at']

    def validate(self, data):
        # amount_paid = amount - discount is computed in Payment.save(); a
        # discount larger than the amount would silently make that negative.
        amount = data.get('amount', getattr(self.instance, 'amount', None))
        discount = data.get('discount', getattr(self.instance, 'discount', 0))
        if amount is not None and discount is not None and discount > amount:
            raise serializers.ValidationError(
                {'discount': 'Discount cannot be greater than the payment amount.'}
            )
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        member = data.get('member', getattr(self.instance, 'member', None))
        membership = data.get('membership', getattr(self.instance, 'membership', None))
        if gym is not None and member is not None:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=gym, user=member, role=GymMembership.Role.MEMBER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
            if not user_has_branch_access(member, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
        if membership is not None:
            if gym is not None and membership.gym_id != gym.id:
                raise serializers.ValidationError({'membership': 'Membership does not belong to this gym.'})
            if member is not None and membership.member_id != member.id:
                raise serializers.ValidationError({'membership': 'Membership does not belong to this member.'})
        return data