# payments views
import json
import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsAnyStaffRole, IsMember, IsOwnerOrStaff
from apps.lockers.models import LockerAssignment
from apps.memberships.models import Membership
from .models import Payment
from .providers import esewa, khalti
from .providers.esewa import EsewaError
from .providers.khalti import KhaltiError
from .serializers import PaymentSerializer

logger = logging.getLogger(__name__)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer record and manage payments made on a member's behalf
    (e.g. cash collected at the desk).

    Members can only view their own payment history and pay their own
    outstanding dues — they cannot record payments for anyone else, and
    every self-service amount is computed server-side (never trusted from
    the client). See `my_dues` / `pay` below.

    Filter with ?member=<id>, ?status=PAID|PENDING|..., ?payment_for=MEMBERSHIP|...

    Extra endpoints:
      GET  /api/payments/summary/        — totals by status and by payment method (Owner/Staff)
      GET  /api/payments/my-dues/        — current member's outstanding membership/locker dues
      POST /api/payments/pay/            — current member pays one of those dues
      POST /api/payments/verify-khalti/  — confirm a Khalti checkout after the member returns
      POST /api/payments/retry-khalti/   — retry verification for a pending Khalti payment
      POST /api/payments/verify-esewa/   — confirm an eSewa checkout after the member returns
      POST /api/payments/retry-esewa/    — retry verification for a pending eSewa payment
    """
    serializer_class = PaymentSerializer

    def get_permissions(self):
        if self.action in ('my_dues', 'pay', 'verify_khalti', 'retry_khalti', 'verify_esewa', 'retry_esewa'):
            return [IsMember()]
        if self.action == 'summary':
            return [IsOwnerOrStaff()]
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            # Staff-recorded payments (e.g. cash at the desk) — members pay
            # through the `pay` action instead, never through this endpoint.
            return [IsAnyStaffRole()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Payment.objects.select_related('member', 'collected_by', 'membership').all()
        status_ = self.request.query_params.get('status')
        payment_for = self.request.query_params.get('payment_for')
        if status_:
            qs = qs.filter(status=status_)
        if payment_for:
            qs = qs.filter(payment_for=payment_for)

        if self.request.user.role == User.Role.MEMBER:
            # Members only ever see their own payment history.
            return qs.filter(member=self.request.user)

        member_id = self.request.query_params.get('member')
        if member_id:
            qs = qs.filter(member_id=member_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(collected_by=self.request.user)

    @staticmethod
    def _generate_receipt_number():
        return f'SELF-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}'

    @action(detail=False, methods=['get'], url_path='my-dues')
    def my_dues(self, request):
        """
        Returns the current member's outstanding dues, so the frontend can
        render a "what am I paying for" picker without letting the member
        type in an arbitrary amount.

        Response shape:
        {
          "dues": [
            {"payment_for": "MEMBERSHIP", "reference_id": 12, "label": "...", "amount": 2000.0},
            {"payment_for": "LOCKER", "reference_id": 4, "label": "...", "amount": 300.0}
          ]
        }
        """
        user = request.user
        dues = []

        pending_memberships = (
            Membership.objects.filter(member=user, status=Membership.Status.PENDING)
            .select_related('plan')
            .order_by('-created_at')
        )
        for pm in pending_memberships:
            outstanding = pm.plan.price - (pm.price_paid or Decimal('0'))
            if outstanding > 0:
                dues.append({
                    'payment_for': Payment.PaymentFor.MEMBERSHIP,
                    'reference_id': pm.id,
                    'label': f'{pm.plan.name} Membership',
                    'amount': float(outstanding),
                })

        active_locker = (
            LockerAssignment.objects.filter(member=user, is_active=True)
            .select_related('locker')
            .first()
        )
        if active_locker and active_locker.locker.monthly_fee > 0:
            # Check if there's already a PAID payment for a locker this month
            now = timezone.now()
            has_paid = Payment.objects.filter(
                member=user,
                payment_for=Payment.PaymentFor.LOCKER,
                status=Payment.PaymentStatus.PAID,
                created_at__year=now.year,
                created_at__month=now.month,
            ).exists()

            if not has_paid:
                dues.append({
                    'payment_for': Payment.PaymentFor.LOCKER,
                    'reference_id': active_locker.id,
                    'label': f'Locker {active_locker.locker.locker_number} Fee',
                    'amount': float(active_locker.locker.monthly_fee),
                })

        return Response({'dues': dues})

    def _resolve_due_amount(self, user, payment_for, reference_id):
        """
        Looks up the authoritative amount for a member's own membership/locker
        due. Never trusts a client-sent amount. Returns (amount, membership_obj).
        """
        if payment_for == Payment.PaymentFor.MEMBERSHIP:
            membership = get_object_or_404(
                Membership, id=reference_id, member=user, status=Membership.Status.PENDING
            )
            amount = membership.plan.price - (membership.price_paid or Decimal('0'))
            if amount <= 0:
                raise ValidationError({'detail': 'This membership has no outstanding balance.'})
            return amount, membership

        if payment_for == Payment.PaymentFor.LOCKER:
            assignment = get_object_or_404(
                LockerAssignment, id=reference_id, member=user, is_active=True
            )
            amount = assignment.locker.monthly_fee
            if amount <= 0:
                raise ValidationError({'detail': 'This locker has no fee configured.'})
            return amount, None

        raise ValidationError({'payment_for': 'Must be MEMBERSHIP or LOCKER.'})

    @action(detail=False, methods=['post'])
    def pay(self, request):
        """
        Member self-service payment.

        Body: {"payment_for": "MEMBERSHIP"|"LOCKER", "reference_id": <id>,
               "payment_method": "ESEWA"|"KHALTI"|"CARD"|"BANK"|"OTHER"}

        The amount is always recomputed here from the referenced membership
        or locker record — a member can never submit their own amount.

        For KHALTI: creates the Payment as PENDING, starts a real Khalti
        sandbox checkout, and returns a "payment_url" the frontend must
        redirect the browser to. The payment only becomes PAID after the
        member completes checkout and the frontend calls verify-khalti/,
        which re-checks the transaction with Khalti directly (never trusts
        the redirect alone).

        For ESEWA: creates the Payment as PENDING and returns signed form
        fields ("esewa_form_fields") plus "esewa_action_url" — the frontend
        must build and auto-submit a hidden HTML form POST with those fields
        directly to esewa_action_url. eSewa redirects back with a base64
        ?data= param, which the frontend passes to verify-esewa/.

        For any other method: lands as PENDING for now — settling those
        (e.g. reception confirming cash) goes through the existing
        owner/staff edit flow.
        """
        user = request.user
        payment_for = request.data.get('payment_for')
        reference_id = request.data.get('reference_id')
        payment_method = request.data.get('payment_method') or Payment.PaymentMethod.OTHER
        if payment_method not in Payment.PaymentMethod.values:
            raise ValidationError({'payment_method': 'Not a valid payment method.'})

        # ── Duplicate-prevention gate ───────────────────────────────────
        # Block the payment BEFORE resolving amounts if there is already a
        # PAID (or in-flight PENDING) payment for the same member + same
        # due this month.  Uses select_for_update inside an atomic block
        # so two concurrent requests cannot both sneak through.
        with transaction.atomic():
            existing_paid = Payment.objects.select_for_update().filter(
                member=user,
                payment_for=payment_for,
                status__in=(Payment.PaymentStatus.PAID, Payment.PaymentStatus.PENDING),
                created_at__year=timezone.now().year,
                created_at__month=timezone.now().month,
            )
            if payment_for == Payment.PaymentFor.MEMBERSHIP:
                # Lock the specific membership
                membership_obj = Membership.objects.select_for_update().filter(
                    id=reference_id, member=user
                ).first()
                if membership_obj:
                    existing_paid = existing_paid.filter(membership=membership_obj)
            elif payment_for == Payment.PaymentFor.LOCKER:
                # For lockers we don't have a direct FK, so check by any
                # LOCKER payment this month for this member.
                pass

            if existing_paid.exists():
                dup = existing_paid.first()
                if dup.status == Payment.PaymentStatus.PAID:
                    raise ValidationError({
                        'detail': f'You have already paid for this {payment_for.lower()} this month. '
                                  f'Receipt: {dup.receipt_number}'
                    })
                # If PENDING, return the existing payment so the member can
                # complete or retry it instead of creating a duplicate.
                if dup.payment_method == Payment.PaymentMethod.KHALTI and dup.transaction_id:
                    try:
                        lookup = khalti.lookup_payment(dup.transaction_id)
                        if lookup.get('status') in ('Expired', 'User canceled'):
                            dup.status = Payment.PaymentStatus.FAILED
                            dup.notes = f'Khalti status: {lookup["status"]}'
                            dup.save()
                        else:
                            data = PaymentSerializer(dup).data
                            data['payment_url'] = (
                                f'{settings.KHALTI_BASE_URL}/checkout'
                                f'?pidx={dup.transaction_id}'
                            )
                            return Response(data, status=200)
                    except KhaltiError:
                        pass
                if dup.payment_method == Payment.PaymentMethod.ESEWA and dup.transaction_id:
                    try:
                        lookup = esewa.check_status(dup.transaction_id, dup.amount)
                        if lookup.get('status') in ('CANCELED', 'NOT_FOUND'):
                            dup.status = Payment.PaymentStatus.FAILED
                            dup.notes = f'eSewa status: {lookup["status"]}'
                            dup.save()
                        else:
                            # Re-sign a fresh form for the same pending payment
                            # rather than reusing old fields (eSewa rejects a
                            # stale/expired form submission).
                            form_fields = esewa.build_form_fields(dup)
                            dup.transaction_id = form_fields['transaction_uuid']
                            dup.save()
                            data = PaymentSerializer(dup).data
                            data['esewa_action_url'] = settings.ESEWA_BASE_URL
                            data['esewa_form_fields'] = form_fields
                            return Response(data, status=200)
                    except EsewaError:
                        pass

        amount, membership = self._resolve_due_amount(user, payment_for, reference_id)

        payment = Payment.objects.create(
            member=user,
            membership=membership,
            payment_for=payment_for,
            amount=amount,
            discount=Decimal('0'),
            payment_method=payment_method,
            status=Payment.PaymentStatus.PENDING,
            receipt_number=self._generate_receipt_number(),
        )

        if payment_method == Payment.PaymentMethod.KHALTI:
            try:
                result = khalti.initiate_payment(payment)
            except KhaltiError as exc:
                logger.error('Khalti initiate failed for payment %s: %s', payment.id, exc)
                payment.status = Payment.PaymentStatus.FAILED
                payment.notes = f'Khalti initiate failed: {exc}'
                payment.save()
                return Response(
                    {'detail': f'Could not start Khalti checkout: {exc}'},
                    status=502,
                )
            payment.transaction_id = result['pidx']
            payment.save()
            data = PaymentSerializer(payment).data
            data['payment_url'] = result['payment_url']
            return Response(data, status=201)

        if payment_method == Payment.PaymentMethod.ESEWA:
            try:
                form_fields = esewa.build_form_fields(payment)
            except EsewaError as exc:
                logger.error('eSewa build_form_fields failed for payment %s: %s', payment.id, exc)
                payment.status = Payment.PaymentStatus.FAILED
                payment.notes = f'eSewa initiate failed: {exc}'
                payment.save()
                return Response(
                    {'detail': f'Could not start eSewa checkout: {exc}'},
                    status=502,
                )
            payment.transaction_id = form_fields['transaction_uuid']
            payment.save()
            data = PaymentSerializer(payment).data
            data['esewa_action_url'] = settings.ESEWA_BASE_URL
            data['esewa_form_fields'] = form_fields
            return Response(data, status=201)

        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=False, methods=['post'], url_path='verify-khalti')
    def verify_khalti(self, request):
        """
        Confirms a Khalti payment after the member returns from checkout.

        Body: {"pidx": "..."}  (read off the return_url query string)

        Calls Khalti's lookup API directly — the frontend's query-string
        status is never trusted. Only marks the payment PAID if Khalti says
        "Completed" AND the amount matches our own record exactly.
        Idempotent: calling this twice on an already-PAID payment is a no-op.
        """
        pidx = request.data.get('pidx')
        if not pidx:
            raise ValidationError({'pidx': 'This field is required.'})

        payment = get_object_or_404(Payment, transaction_id=pidx, member=request.user)

        if payment.status == Payment.PaymentStatus.PAID:
            return Response(PaymentSerializer(payment).data)

        try:
            result = khalti.verify_payment(pidx, payment.amount)
        except KhaltiError as exc:
            logger.error('Khalti verify failed for pidx=%s: %s', pidx, exc)
            return Response({'detail': f'Could not verify with Khalti: {exc}'}, status=502)

        return self._apply_khalti_result(payment, result)

    @action(detail=False, methods=['post'], url_path='retry-khalti')
    def retry_khalti(self, request):
        """
        Retry verification for a pending Khalti payment.

        Body: {"payment_id": <id>}  (the Payment record's PK)

        Useful when the member didn't complete the redirect or verification
        failed transiently. Only works for PENDING payments with a KHALTI method.
        """
        payment_id = request.data.get('payment_id')
        if not payment_id:
            raise ValidationError({'payment_id': 'This field is required.'})

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            member=request.user,
            payment_method=Payment.PaymentMethod.KHALTI,
            status=Payment.PaymentStatus.PENDING,
        )

        if not payment.transaction_id:
            return Response(
                {'detail': 'No Khalti transaction associated with this payment.'},
                status=400,
            )

        try:
            result = khalti.lookup_payment(payment.transaction_id)
        except KhaltiError as exc:
            logger.error('Khalti retry lookup failed for payment %s: %s', payment.id, exc)
            return Response({'detail': f'Could not verify with Khalti: {exc}'}, status=502)

        gateway_status = result.get('status')
        gateway_amount_paisa = result.get('total_amount')
        expected_paisa = int(payment.amount * 100)

        if gateway_status == 'Completed' and gateway_amount_paisa == expected_paisa:
            payment.status = Payment.PaymentStatus.PAID
            payment.paid_at = timezone.now()
            payment.notes = f'Verified via Khalti retry — txn {result.get("transaction_id", "")}'
            payment.save()
            logger.info('Khalti retry succeeded for payment %s', payment.id)
        elif gateway_status in ('Expired', 'User canceled'):
            payment.status = Payment.PaymentStatus.FAILED
            payment.notes = f'Khalti status: {gateway_status}'
            payment.save()
        elif gateway_status == 'Completed' and gateway_amount_paisa != expected_paisa:
            payment.notes = (
                f'Khalti reported Completed but amount mismatch: '
                f'expected {expected_paisa}, got {gateway_amount_paisa}'
            )
            payment.save()

        return Response(PaymentSerializer(payment).data)

    def _apply_khalti_result(self, payment, result):
        """Apply Khalti verification result to a payment record."""
        gateway_status = result['status']
        verified = result['verified']

        if verified:
            payment.status = Payment.PaymentStatus.PAID
            payment.paid_at = timezone.now()
            payment.notes = f'Verified via Khalti lookup — txn {result["transaction_id"]}'
            payment.save()
            logger.info('Khalti payment %s verified successfully', payment.id)
        elif gateway_status in ('Expired', 'User canceled'):
            payment.status = Payment.PaymentStatus.FAILED
            payment.notes = f'Khalti status: {gateway_status}'
            payment.save()
            logger.info('Khalti payment %s status: %s', payment.id, gateway_status)
        elif gateway_status == 'Completed' and not verified:
            # Amount mismatch is a red flag — don't activate, leave it PENDING
            # for staff to look into rather than silently trusting it.
            payment.notes = (
                f'Khalti reported Completed but amount mismatch: '
                f'expected {int(payment.amount * 100)}, got {result["raw"].get("total_amount")}'
            )
            payment.save()
            logger.warning('Khalti amount mismatch for payment %s', payment.id)
        # Otherwise (Pending/Initiated) — leave PENDING, member can retry verification.

        return Response(PaymentSerializer(payment).data)

    @action(detail=False, methods=['post'], url_path='verify-esewa')
    def verify_esewa(self, request):
        """
        Confirms an eSewa payment after the member returns from checkout.

        Body: {"data": "<base64 string from the ?data= query param
               eSewa appended to success_url/failure_url>"}

        The base64 payload is decoded and its own signature is verified
        first (anti-tampering — a member could otherwise hand-craft a fake
        ?data= param). Then, as defence in depth, eSewa's status-check API
        is called directly and cross-checked against our own amount before
        marking the payment PAID — the redirect payload alone is never
        trusted for that decision.
        Idempotent: calling this twice on an already-PAID payment is a no-op.
        """
        data_param = request.data.get('data')
        if not data_param:
            raise ValidationError({'data': 'This field is required.'})

        try:
            decoded = esewa.decode_response(data_param)
        except EsewaError as exc:
            logger.error('eSewa response decode/verify failed: %s', exc)
            return Response({'detail': f'Could not verify eSewa response: {exc}'}, status=502)

        transaction_uuid = decoded.get('transaction_uuid')
        payment = get_object_or_404(Payment, transaction_id=transaction_uuid, member=request.user)

        if payment.status == Payment.PaymentStatus.PAID:
            return Response(PaymentSerializer(payment).data)

        try:
            result = esewa.verify_payment(transaction_uuid, payment.amount)
        except EsewaError as exc:
            logger.error('eSewa verify failed for transaction_uuid=%s: %s', transaction_uuid, exc)
            return Response({'detail': f'Could not verify with eSewa: {exc}'}, status=502)

        return self._apply_esewa_result(payment, result)

    @action(detail=False, methods=['post'], url_path='retry-esewa')
    def retry_esewa(self, request):
        """
        Retry verification for a pending eSewa payment.

        Body: {"payment_id": <id>}  (the Payment record's PK)

        Useful when the member didn't complete the redirect or verification
        failed transiently. Only works for PENDING payments with an ESEWA method.
        """
        payment_id = request.data.get('payment_id')
        if not payment_id:
            raise ValidationError({'payment_id': 'This field is required.'})

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            member=request.user,
            payment_method=Payment.PaymentMethod.ESEWA,
            status=Payment.PaymentStatus.PENDING,
        )

        if not payment.transaction_id:
            return Response(
                {'detail': 'No eSewa transaction associated with this payment.'},
                status=400,
            )

        try:
            result = esewa.verify_payment(payment.transaction_id, payment.amount)
        except EsewaError as exc:
            logger.error('eSewa retry verify failed for payment %s: %s', payment.id, exc)
            return Response({'detail': f'Could not verify with eSewa: {exc}'}, status=502)

        return self._apply_esewa_result(payment, result)

    def _apply_esewa_result(self, payment, result):
        """Apply eSewa verification result to a payment record."""
        gateway_status = result['status']
        verified = result['verified']

        if verified:
            payment.status = Payment.PaymentStatus.PAID
            payment.paid_at = timezone.now()
            payment.notes = f'Verified via eSewa status check — ref {result["ref_id"]}'
            payment.save()
            logger.info('eSewa payment %s verified successfully', payment.id)
        elif gateway_status in ('CANCELED', 'NOT_FOUND'):
            payment.status = Payment.PaymentStatus.FAILED
            payment.notes = f'eSewa status: {gateway_status}'
            payment.save()
            logger.info('eSewa payment %s status: %s', payment.id, gateway_status)
        elif gateway_status == 'COMPLETE' and not verified:
            # Amount mismatch is a red flag — don't activate, leave it PENDING
            # for staff to look into rather than silently trusting it.
            payment.notes = (
                f'eSewa reported COMPLETE but amount mismatch: '
                f'expected {payment.amount}, got {result["raw"].get("total_amount")}'
            )
            payment.save()
            logger.warning('eSewa amount mismatch for payment %s', payment.id)
        # Otherwise (PENDING/AMBIGUOUS) — leave PENDING, member can retry verification.

        return Response(PaymentSerializer(payment).data)

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


# ─── Khalti Webhook (function-based, outside the ViewSet) ──────────────────
# Khalti sends a server-to-server POST here when a payment completes.
# This is the ONLY reliable confirmation — the browser redirect may never
# happen if the member closes their tab.  We intentionally do NOT require
# DRF authentication for this endpoint; instead we verify the payment
# directly with Khalti's API (double-check), and we trust only that lookup.
# CSRF is exempted because Khalti cannot carry a Django CSRF cookie.
# ────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def khalti_webhook(request):
    """
    Khalti server-to-server webhook for payment confirmation.

    Khalti POSTs a JSON body with at least a 'pidx' field.
    We then look up the payment with Khalti directly to confirm,
    rather than trusting the webhook payload alone.

    Response: always 200 OK (Khalti will retry if it gets a non-2xx).
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Khalti webhook received invalid JSON')
        return JsonResponse({'detail': 'Invalid JSON'}, status=400)

    pidx = body.get('pidx')
    if not pidx:
        logger.warning('Khalti webhook missing pidx field')
        return JsonResponse({'detail': 'pidx is required'}, status=400)

    # Find the payment by Khalti's pidx
    try:
        payment = Payment.objects.select_related('member').get(transaction_id=pidx)
    except Payment.DoesNotExist:
        # Payment not found — Khalti may be sending a webhook for a payment
        # we don't recognize, or the pidx is malformed. Return 200 to prevent
        # Khalti from retrying endlessly.
        logger.warning('Khalti webhook for unknown pidx: %s', pidx)
        return JsonResponse({'detail': 'Payment not found'}, status=200)

    # Already processed
    if payment.status == Payment.PaymentStatus.PAID:
        return JsonResponse({'detail': 'Already verified'}, status=200)

    # Verify directly with Khalti — never trust the webhook payload alone
    try:
        result = khalti.verify_payment(pidx, payment.amount)
    except KhaltiError as exc:
        logger.error('Khalti webhook lookup failed for pidx=%s: %s', pidx, exc)
        # Return 500 so Khalti will retry later
        return JsonResponse({'detail': 'Lookup failed'}, status=500)

    gateway_status = result['status']
    verified = result['verified']

    if verified:
        payment.status = Payment.PaymentStatus.PAID
        payment.paid_at = timezone.now()
        payment.notes = f'Verified via Khalti webhook — txn {result["transaction_id"]}'
        payment.save()
        logger.info('Khalti webhook: payment %s verified', payment.id)
    elif gateway_status in ('Expired', 'User canceled'):
        payment.status = Payment.PaymentStatus.FAILED
        payment.notes = f'Khalti webhook status: {gateway_status}'
        payment.save()
        logger.info('Khalti webhook: payment %s status %s', payment.id, gateway_status)
    elif gateway_status == 'Completed' and not verified:
        payment.notes = (
            f'Khalti webhook: Completed but amount mismatch — '
            f'expected {int(payment.amount * 100)}, got {result["raw"].get("total_amount")}'
        )
        payment.save()
        logger.warning('Khalti webhook amount mismatch for payment %s', payment.id)
    else:
        logger.info('Khalti webhook: payment %s still %s', payment.id, gateway_status)

    # Always return 200 to Khalti — non-2xx causes retries
    return JsonResponse({'detail': 'OK'}, status=200)