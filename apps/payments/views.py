# payments views
from django.db.models import Sum, Count
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsAnyStaffRole, IsOwnerOrStaff
from .models import Payment
from .serializers import PaymentSerializer


class PaymentViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer record and manage payments.
    Filter with ?member=<id>, ?status=PAID|PENDING|..., ?payment_for=MEMBERSHIP|...

    Extra endpoint:
      GET /api/payments/summary/  — totals by status and by payment method
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

    @action(detail=False, methods=['get'], permission_classes=[IsOwnerOrStaff])
    def summary(self, request):
        """
        Returns aggregate totals for the payments dashboard stat cards.

        Response shape:
        {
          "total_collected":  <sum of amount_paid for PAID payments>,
          "total_pending":    <sum of amount for PENDING payments>,
          "total_count":      <total number of payment records>,
          "by_method": {
            "CASH": <sum of amount_paid>,
            "ESEWA": ...,
            ...
          },
          "by_status": {
            "PAID": { "count": N, "total": X },
            "PENDING": { "count": N, "total": X },
            ...
          }
        }
        """
        qs = Payment.objects.all()

        # Optional date range filters: ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        total_collected = (
            qs.filter(status=Payment.PaymentStatus.PAID)
              .aggregate(total=Sum('amount_paid'))['total'] or 0
        )
        total_pending = (
            qs.filter(status=Payment.PaymentStatus.PENDING)
              .aggregate(total=Sum('amount'))['total'] or 0
        )
        total_count = qs.count()

        # Breakdown by payment method — single query grouped by method
        method_rows = (
            qs.filter(status=Payment.PaymentStatus.PAID)
              .values('payment_method')
              .annotate(total=Sum('amount_paid'))
        )
        by_method = {row['payment_method']: float(row['total'] or 0) for row in method_rows}
        # Ensure every defined method key is present, even if it has no data
        for method, _ in Payment.PaymentMethod.choices:
            by_method.setdefault(method, 0.0)

        # Breakdown by status — single query grouped by status
        status_rows = (
            qs.values('status')
              .annotate(count=Count('id'), total=Sum('amount_paid'))
        )
        by_status = {
            row['status']: {'count': row['count'], 'total': float(row['total'] or 0)}
            for row in status_rows
        }
        # Ensure every defined status key is present
        for st, _ in Payment.PaymentStatus.choices:
            by_status.setdefault(st, {'count': 0, 'total': 0.0})

        return Response({
            'total_collected': float(total_collected),
            'total_pending': float(total_pending),
            'total_count': total_count,
            'by_method': by_method,
            'by_status': by_status,
        })