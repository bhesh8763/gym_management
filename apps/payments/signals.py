"""
Payment signals.

PAYMENT_RECEIVED is fired whenever a Payment is saved with a PAID or PARTIAL
status.  The notification is idempotent: if one was already sent today for the
same payment (e.g. due to a double-save or an update) it won't create a second
one.
"""
from decimal import Decimal

from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment


@receiver(post_save, sender=Payment)
def activate_membership_on_payment(sender, instance, created, **kwargs):
    """
    When a membership payment is confirmed as PAID, activate the linked
    membership and update its price_paid field.

    PARTIAL payments also accumulate into ``price_paid`` so members can pay
    a membership off in instalments; the membership only activates once the
    plan price is fully covered.
    """
    if instance.payment_for != Payment.PaymentFor.MEMBERSHIP:
        return
    if not instance.membership_id:
        return

    from apps.memberships.models import Membership

    membership_lookup = {'id': instance.membership_id}
    if instance.gym_id:
        membership_lookup['gym_id'] = instance.gym_id
    membership = Membership.objects.filter(**membership_lookup).first()
    if not membership:
        return

    # Recompute the accumulated total across ALL confirmed payments for this    # membership (PAID + PARTIAL). Recomputing — rather than incrementing —    # keeps the number correct even if a payment is later edited or refunded.
    confirmed_total = Payment.objects.filter(
        membership_id=membership.id,
        status__in=(Payment.PaymentStatus.PAID, Payment.PaymentStatus.PARTIAL),
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0')

    update_fields = []
    fully_paid = confirmed_total >= membership.plan.price
    if membership.status == Membership.Status.PENDING and fully_paid:
        membership.status = Membership.Status.ACTIVE
        update_fields.append('status')

    # Track how much has actually been collected so far.
    membership.price_paid = confirmed_total
    update_fields.append('price_paid')

    if update_fields:
        membership.save(update_fields=update_fields)


@receiver(post_save, sender=Payment)
def notify_payment_received(sender, instance, created, **kwargs):
    """
    Create a PAYMENT_RECEIVED notification for the member whenever a payment
    lands in PAID or PARTIAL status.

    Deferred import of Notification avoids a circular-import between the
    payments and notifications apps at module load time.
    """
    from django.utils import timezone
    from apps.notifications.models import Notification

    # Only react to PAID / PARTIAL payments
    if instance.status not in (Payment.PaymentStatus.PAID, Payment.PaymentStatus.PARTIAL):
        return

    # Idempotency guard: skip if we already sent this notification today.
    # localdate() matches what created_at__date resolves against (the current
    # timezone), whereas now().date() is UTC — comparing the two breaks
    # between 18:15 UTC and midnight UTC (i.e. after midnight in Kathmandu).
    today = timezone.localdate()
    already_sent = Notification.objects.filter(
        gym=instance.gym,
        recipient_id=instance.member_id,
        notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        related_payment_id=instance.id,
        created_at__date=today,
    ).exists()
    if already_sent:
        return

    status_label = 'received' if instance.status == Payment.PaymentStatus.PAID else 'partially received'
    Notification.objects.create(
        gym=instance.gym,
        branch=instance.branch,
        recipient_id=instance.member_id,
        notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        title='Payment received',
        message=(
            f'Your payment of NPR {instance.amount_paid} for receipt '
            f'#{instance.receipt_number} has been {status_label}. '
            f'Thank you!'
        ),
        related_payment_id=instance.id,
    )
