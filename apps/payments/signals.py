"""
Payment signals.

PAYMENT_RECEIVED is fired whenever a Payment is saved with a PAID or PARTIAL
status.  The notification is idempotent: if one was already sent today for the
same payment (e.g. due to a double-save or an update) it won't create a second
one.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Payment


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

    # Idempotency guard: skip if we already sent this notification today
    today = timezone.now().date()
    already_sent = Notification.objects.filter(
        recipient_id=instance.member_id,
        notification_type=Notification.NotificationType.PAYMENT_RECEIVED,
        related_payment_id=instance.id,
        created_at__date=today,
    ).exists()
    if already_sent:
        return

    status_label = 'received' if instance.status == Payment.PaymentStatus.PAID else 'partially received'
    Notification.objects.create(
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
