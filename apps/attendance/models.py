"""
Attendance tracking for both members and staff/trainers.
"""
import secrets
from datetime import datetime
from django.conf import settings
from django.db import models
from django.utils import timezone


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
            # Combine with a dummy date so we can subtract directly
            dummy = datetime(2000, 1, 1)
            t1 = datetime.combine(dummy, self.check_in)
            t2 = datetime.combine(dummy, self.check_out)
            return int((t2 - t1).total_seconds() / 60)
        return None


class QRAttendanceToken(models.Model):
    """
    A persistent QR code token assigned to each member.
    Scanning the token creates or updates the Attendance record for that day.
    """
    member = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='qr_attendance_token',
        limit_choices_to={'role': 'MEMBER'},
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'qr_attendance_tokens'
        verbose_name = 'QR Attendance Token'

    def __str__(self):
        return f'QR token for {self.member.get_full_name()}'

    @classmethod
    def get_or_create_for_member(cls, member):
        """Return existing token or create a new one."""
        obj, _ = cls.objects.get_or_create(
            member=member,
            defaults={'token': secrets.token_urlsafe(48)},
        )
        return obj

    def regenerate(self):
        """Issue a fresh token (e.g., if the old one was lost/compromised)."""
        self.token = secrets.token_urlsafe(48)
        self.save(update_fields=['token', 'updated_at'])
        return self
