"""
auto_reject_expired_leaves

Rejects all PENDING leave requests whose end_date is before today.
These are requests that were never reviewed in time.

Run via:
    python manage.py auto_reject_expired_leaves

Can be scheduled via cron to run daily, e.g.:
    0 0 * * * cd /path/to/project && python manage.py auto_reject_expired_leaves
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.staff.models import LeaveRequest

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Auto-reject pending leave requests whose end_date has passed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually updating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()

        expired = LeaveRequest.objects.filter(
            status=LeaveRequest.LeaveStatus.PENDING,
            end_date__lt=today,
        )

        count = expired.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No expired pending leave requests.'))
            return

        self.stdout.write(f'Found {count} expired pending leave request(s):')

        for leave in expired:
            requester = leave.requester.get_full_name() or leave.requester.username
            self.stdout.write(
                f'  #{leave.id} {requester} — '
                f'{leave.leave_type} {leave.start_date} to {leave.end_date}'
            )
            if not dry_run:
                leave.status = LeaveRequest.LeaveStatus.REJECTED
                leave.review_note = (
                    'Auto-rejected: leave end date passed without review.'
                )
                leave.save()
                self.stdout.write(self.style.SUCCESS(f'    -> REJECTED'))

        summary = f'\nDone. Auto-rejected: {count} leave request(s).'
        if dry_run:
            summary = f'[DRY RUN] {summary}'

        self.stdout.write(self.style.SUCCESS(summary))
