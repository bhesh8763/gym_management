"""
Generates automated notifications for:
  - Membership renewals (expiring within REMINDER_WINDOW_DAYS)
  - Payments that are pending/overdue
  - Member inactivity (no attendance in INACTIVITY_THRESHOLD_DAYS)

Run manually:
    python manage.py send_reminders

Run daily via cron / Windows Task Scheduler, e.g.:
    0 8 * * * cd /path/to/project && venv/bin/python manage.py send_reminders

Idempotent: skips creating a duplicate reminder if one was already sent
today for the same user + type + related object.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.attendance.models import Attendance
from apps.memberships.models import Membership
from apps.notifications.models import Notification
from apps.payments.models import Payment

REMINDER_WINDOW_DAYS = 3      # send a renewal reminder this many days before expiry
INACTIVITY_THRESHOLD_DAYS = 14  # flag a member inactive after this many days with no check-in


class Command(BaseCommand):
    help = 'Generate membership renewal, payment due, and inactivity notifications.'

    def handle(self, *args, **options):
        today = timezone.now().date()

        renewal_count = self._send_membership_renewal_reminders(today)
        payment_count = self._send_payment_due_reminders(today)
        inactivity_count = self._send_inactivity_alerts(today)

        self.stdout.write(self.style.SUCCESS(
            f'Done. Created {renewal_count} renewal, {payment_count} payment-due, '
            f'{inactivity_count} inactivity notifications.'
        ))

    # ── Membership renewal / expiry ─────────────────────────────────────────
    def _send_membership_renewal_reminders(self, today):
        window_end = today + timedelta(days=REMINDER_WINDOW_DAYS)
        count = 0

        expiring = Membership.objects.filter(
            status=Membership.Status.ACTIVE,
            end_date__gte=today,
            end_date__lte=window_end,
        )
        for membership in expiring:
            if self._already_sent_today(
                membership.member_id, Notification.NotificationType.MEMBERSHIP_RENEWAL,
                related_membership_id=membership.id,
            ):
                continue
            days_left = (membership.end_date - today).days
            Notification.objects.create(
                recipient_id=membership.member_id,
                notification_type=Notification.NotificationType.MEMBERSHIP_RENEWAL,
                title='Membership renewal reminder',
                message=(
                    f'Your "{membership.plan.name}" membership expires in {days_left} '
                    f'day(s) on {membership.end_date}. Renew soon to avoid interruption.'
                ),
                related_membership_id=membership.id,
            )
            count += 1

        # Already-expired memberships that are still marked ACTIVE (not yet swept)
        expired = Membership.objects.filter(status=Membership.Status.ACTIVE, end_date__lt=today)
        for membership in expired:
            membership.status = Membership.Status.EXPIRED
            membership.save(update_fields=['status'])
            if self._already_sent_today(
                membership.member_id, Notification.NotificationType.MEMBERSHIP_EXPIRY,
                related_membership_id=membership.id,
            ):
                continue
            Notification.objects.create(
                recipient_id=membership.member_id,
                notification_type=Notification.NotificationType.MEMBERSHIP_EXPIRY,
                title='Membership expired',
                message=f'Your "{membership.plan.name}" membership expired on {membership.end_date}.',
                related_membership_id=membership.id,
            )
            count += 1

        return count

    # ── Payment due ──────────────────────────────────────────────────────────
    def _send_payment_due_reminders(self, today):
        count = 0
        pending = Payment.objects.filter(
            status__in=[Payment.PaymentStatus.PENDING, Payment.PaymentStatus.PARTIAL]
        )
        for payment in pending:
            if self._already_sent_today(
                payment.member_id, Notification.NotificationType.PAYMENT_DUE,
                related_payment_id=payment.id,
            ):
                continue
            outstanding = payment.amount - payment.discount
            Notification.objects.create(
                recipient_id=payment.member_id,
                notification_type=Notification.NotificationType.PAYMENT_DUE,
                title='Payment due',
                message=(
                    f'You have a payment of NPR {outstanding} due '
                    f'on receipt #{payment.receipt_number}.'
                ),
                related_payment_id=payment.id,
            )
            count += 1
        return count

    # ── Inactivity ───────────────────────────────────────────────────────────
    def _send_inactivity_alerts(self, today):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cutoff = today - timedelta(days=INACTIVITY_THRESHOLD_DAYS)
        count = 0

        active_members = User.objects.filter(role=User.Role.MEMBER, is_active=True)
        for member in active_members:
            last_visit = (
                Attendance.objects.filter(user=member).order_by('-date').values_list('date', flat=True).first()
            )
            if last_visit is not None and last_visit >= cutoff:
                continue  # visited recently, nothing to do
            if last_visit is None:
                continue  # never checked in at all — not an "inactivity" case, skip for now

            if self._already_sent_today(member.id, Notification.NotificationType.INACTIVITY):
                continue

            days_absent = (today - last_visit).days
            Notification.objects.create(
                recipient_id=member.id,
                notification_type=Notification.NotificationType.INACTIVITY,
                title='We miss you at the gym!',
                message=f"You haven't checked in for {days_absent} days. Come back and keep your progress going!",
            )
            count += 1
        return count

    # ── Helper ───────────────────────────────────────────────────────────────
    @staticmethod
    def _already_sent_today(recipient_id, notification_type, related_membership_id=None, related_payment_id=None):
        today = timezone.now().date()
        qs = Notification.objects.filter(
            recipient_id=recipient_id,
            notification_type=notification_type,
            created_at__date=today,
        )
        if related_membership_id is not None:
            qs = qs.filter(related_membership_id=related_membership_id)
        if related_payment_id is not None:
            qs = qs.filter(related_payment_id=related_payment_id)
        return qs.exists()
