# payments views
from rest_framework import viewsets
from apps.accounts.permissions import IsAnyStaffRole
from .models import Payment
from .serializers import PaymentSerializer


class PaymentViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer record and manage payments.
    Filter with ?member=<id>, ?status=PAID|PENDING|..., ?payment_for=MEMBERSHIP|...
    """
    serializer_class = PaymentSerializer
    permission_classes = [IsAnyStaffRole]

    def get_queryset(self):
        qs = Payment.objects.select_related('member', 'collected_by', 'membership').all()
        member_id = self.request.query_params.get('member')
        status_ = self.request.query_params.get('status')
        payment_for = self.request.query_params.get('payment_for')
        if member_id:
            qs = qs.filter(member_id=member_id)
        if status_:
            qs = qs.filter(status=status_)
        if payment_for:
            qs = qs.filter(payment_for=payment_for)
        return qs

    def perform_create(self, serializer):
        serializer.save(collected_by=self.request.user)