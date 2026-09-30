"""
expire_stale_khalti_payments

Checks all PENDING Khalti payments older than 30 minutes against Khalti's
lookup API. Marks them as FAILED if Khalti says they're expired/canceled,
or leaves them PENDING if still in-progress.

Run via:
    python manage.py expire_stale_khalti_payments

Can be scheduled via cron or a Django signal to run periodically.
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.models import Payment
from apps.payments.providers import khalti
from apps.payments.providers.khalti import KhaltiError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Expire stale PENDING Khalti payments by checking Khalti lookup API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=30,
            help='Only check payments older than N minutes (default: 30)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually updating',
        )

    def handle(self, *args, **options):
        minutes = options['minutes']
        dry_run = options['dry_run']
        cutoff = timezone.now() - timezone.timedelta(minutes=minutes)

        stale_payments = Payment.objects.filter(
            payment_method=Payment.PaymentMethod.KHALTI,
            status=Payment.PaymentStatus.PENDING,
            created_at__lt=cutoff,
            transaction_id__isnull=False,
        ).exclude(transaction_id='')

        count = stale_payments.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS(f'No stale Khalti payments older than {minutes} minutes.'))
            return

        self.stdout.write(f'Checking {count} stale Khalti payment(s)...')
        expired = 0
        verified = 0
        pending = 0
        errors = 0

        for payment in stale_payments:
            try:
                result = khalti.lookup_payment(payment.transaction_id)
            except KhaltiError as exc:
                logger.error('Lookup failed for payment %s: %s', payment.id, exc)
                errors += 1
                continue

            status = result.get('status')
            if status in ('Expired', 'User canceled'):
                expired += 1
                if not dry_run:
                    payment.status = Payment.PaymentStatus.FAILED
                    payment.notes = f'Auto-expired via cron: Khalti status {status}'
                    payment.save()
                self.stdout.write(
                    f'  {payment.receipt_number} -> FAILED ({status})'
                )
            elif status == 'Completed':
                gateway_amount = result.get('total_amount')
                expected = int(payment.amount * 100)
                if gateway_amount == expected:
                    verified += 1
                    if not dry_run:
                        payment.status = Payment.PaymentStatus.PAID
                        payment.paid_at = timezone.now()
                        payment.notes = f'Auto-verified via cron — txn {result.get("transaction_id", "")}'
                        payment.save()
                    self.stdout.write(
                        f'  {payment.receipt_number} -> PAID (txn {result.get("transaction_id", "")})'
                    )
                else:
                    pending += 1
                    self.stdout.write(
                        f'  {payment.receipt_number} -> AMOUNT MISMATCH (expected {expected}, got {gateway_amount})'
                    )
            else:
                pending += 1
                self.stdout.write(
                    f'  {payment.receipt_number} -> still {status}'
                )

        summary = (
            f'\nDone. Verified: {verified}, Expired: {expired}, '
            f'Still pending: {pending}, Errors: {errors}'
        )
        if dry_run:
            summary = f'[DRY RUN] {summary}'

        self.stdout.write(self.style.SUCCESS(summary))
