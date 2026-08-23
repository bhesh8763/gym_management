"""
Management command to send scheduled notifications.

Run daily via cron or Django-Celery-Beat:
    python manage.py send_scheduled_notifications

What it does:
    1. Warns members whose membership expires in 7, 3, or 1 day(s)
    2. Alerts about pending payments overdue by 3+ days
    3. Sends inactivity alerts to members who haven't attended in 14+ days
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.memberships.models import Membership
from apps.payments.models import Payment
from apps.attendance.models import Attendance
from apps.notifications.services import (
    notify_membership_expiry_warning,
    notify_payment_due,
    notify,
)
from apps.notifications.models import Notification


class Command(BaseCommand):
    help = 'Send scheduled notifications (membership expiry, payment due, inactivity)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()
        sent_count = 0

        self.stdout.write(self.style.NOTICE(f'Running scheduled notifications for {today}...'))

        # ── 1. Membership Expiry Warnings ──────────────────────────────────────
        self.stdout.write('\n--- Membership Expiry Warnings ---')
        expiry_warning_days = [7, 3, 1]

        for days in expiry_warning_days:
            target_date = today + timedelta(days=days)
            memberships = Membership.objects.filter(
                status=Membership.Status.ACTIVE,
                end_date=target_date,
            ).select_related('member', 'plan')

            for membership in memberships:
                # Check if we already sent this warning today
                already_sent = Notification.objects.filter(
                    recipient=membership.member,
                    notification_type=Notification.NotificationType.MEMBERSHIP_EXPIRY,
                    created_at__date=today,
                    title__contains=f'{days} day' if days > 1 else 'tomorrow',
                ).exists()

                if already_sent:
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  [DRY RUN] Would send expiry warning to {membership.member.get_full_name()} '
                        f'({days} days left, {membership.plan.name})'
                    )
                else:
                    notify_membership_expiry_warning(
                        recipient=membership.member,
                        days_left=days,
                        plan_name=membership.plan.name,
                        end_date=membership.end_date,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✅ Sent expiry warning to {membership.member.get_full_name()} '
                            f'({days} days left)'
                        )
                    )
                sent_count += 1

        # ── 2. Pending Payment Reminders ───────────────────────────────────────
        self.stdout.write('\n--- Pending Payment Reminders ---')
        pending_payments = Payment.objects.filter(
            status=Payment.PaymentStatus.PENDING,
            created_at__date__lte=today - timedelta(days=3),
        ).select_related('member')

        for payment in pending_payments:
            days_overdue = (today - payment.created_at.date()).days

            # Check if we already sent a reminder today
            already_sent = Notification.objects.filter(
                recipient=payment.member,
                notification_type=Notification.NotificationType.PAYMENT_DUE,
                created_at__date=today,
                related_payment_id=payment.id,
            ).exists()

            if already_sent:
                continue

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would send payment reminder to {payment.member.get_full_name()} '
                    f'(NPR {payment.amount}, {days_overdue} days overdue)'
                )
            else:
                notify_payment_due(
                    recipient=payment.member,
                    amount=payment.amount,
                    payment_for=payment.get_payment_for_display(),
                    days_overdue=days_overdue,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ Sent payment reminder to {payment.member.get_full_name()} '
                        f'(NPR {payment.amount})'
                    )
                )
            sent_count += 1

        # ── 3. Inactivity Alerts ───────────────────────────────────────────────
        self.stdout.write('\n--- Inactivity Alerts ---')
        inactive_threshold = today - timedelta(days=14)

        # Find members with active memberships who haven't attended in 14+ days
        from django.contrib.auth import get_user_model
        User = get_user_model()

        active_member_ids = Membership.objects.filter(
            status=Membership.Status.ACTIVE,
        ).values_list('member_id', flat=True).distinct()

        # Members who HAVE attended recently
        recent_attendee_ids = Attendance.objects.filter(
            date__gte=inactive_threshold,
        ).values_list('user_id', flat=True).distinct()

        # Members who are inactive (active membership but no recent attendance)
        inactive_member_ids = set(active_member_ids) - set(recent_attendee_ids)

        for member_id in inactive_member_ids:
            try:
                member = User.objects.get(pk=member_id, role=User.Role.MEMBER)
            except User.DoesNotExist:
                continue

            # Check if we already sent an inactivity alert this week
            week_ago = today - timedelta(days=7)
            already_sent = Notification.objects.filter(
                recipient=member,
                notification_type=Notification.NotificationType.INACTIVITY,
                created_at__date__gte=week_ago,
            ).exists()

            if already_sent:
                continue

            # Check how long they've been inactive
            last_attendance = Attendance.objects.filter(
                user=member,
            ).order_by('-date').first()

            days_inactive = (today - last_attendance.date).days if last_attendance else 999

            title = 'We miss you at FitCore!'
            message = (
                f"It's been {days_inactive} days since your last visit. "
                f"Your fitness journey is important to us — come back and let's keep going!"
            )

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would send inactivity alert to {member.get_full_name()} '
                    f'({days_inactive} days inactive)'
                )
            else:
                notify(
                    recipient=member,
                    notification_type=Notification.NotificationType.INACTIVITY,
                    title=title,
                    message=message,
                    send_email=True,
                    send_sms=False,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✅ Sent inactivity alert to {member.get_full_name()} '
                        f'({days_inactive} days inactive)'
                    )
                )
            sent_count += 1

        # ── Summary ────────────────────────────────────────────────────────────
        self.stdout.write(f'\n{"=" * 50}')
        mode = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(f'{mode}Done! {sent_count} notification(s) processed.')
        )
