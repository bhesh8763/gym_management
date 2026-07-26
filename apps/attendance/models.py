"""
Attendance tracking for both members and staff/trainers.
"""
from django.conf import settings
from django.db import models


class Attendance(models.Model):
    """
    Records a single attendance event for any user.
    Staff mark attendance manually through the dashboard.
    """

    class AttendanceType(models.TextChoices):
        MEMBER = 'MEMBER', 'Member'
        STAFF = 'STAFF', 'Staff'
        TRAINER = 'TRAINER', 'Trainer'

    class Status(models.TextChoices):
        PRESENT = 'PRESENT', 'Present'
        ABSENT = 'ABSENT', 'Absent'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    attendance_type = models.CharField(
        max_length=10, choices=AttendanceType.choices, db_index=True
    )
    date = models.DateField(db_index=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PRESENT, db_index=True,
    )
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='attendance_marked',
        help_text='Staff/Owner who recorded this attendance',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'attendance'
        verbose_name = 'Attendance'
        verbose_name_plural = 'Attendance Records'
        ordering = ['-date', '-check_in']
        # Prevent duplicate check-in for same user on same date
        unique_together = [('user', 'date')]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.date}'

    @property
    def duration_minutes(self):
        """Calculate time spent if check_out is recorded."""
        if self.check_in and self.check_out:
            from datetime import datetime, timedelta
            fmt = '%H:%M:%S'
            t1 = datetime.strptime(str(self.check_in), fmt)
            t2 = datetime.strptime(str(self.check_out), fmt)
            delta = t2 - t1
            return int(delta.total_seconds() / 60)
        return None