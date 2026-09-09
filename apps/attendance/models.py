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
        indexes = [
            models.Index(fields=['date', 'attendance_type'], name='idx_attendance_date_type'),
            models.Index(fields=['date', 'status'], name='idx_attendance_date_status'),
        ]

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


class BiometricRecord(models.Model):
    """
    Stores biometric data for members to support fingerprint/face recognition
    attendance via a separate biometric scanner device.

    The actual biometric template data (fingerprint hash, face encoding) is
    NOT stored here for security/privacy — this model tracks reference IDs
    that biometric hardware systems use to link a member to their biometric
    profile in the scanner's secure store.
    """

    class BiometricType(models.TextChoices):
        FINGERPRINT = 'FINGERPRINT', 'Fingerprint'
        FACE = 'FACE', 'Face Recognition'
        IRIS = 'IRIS', 'Iris Scan'
        OTHER = 'OTHER', 'Other'

    class BiometricStatus(models.TextChoices):
        NOT_ENROLLED = 'NOT_ENROLLED', 'Not Enrolled'
        ENROLLED = 'ENROLLED', 'Enrolled'
        FAILED = 'FAILED', 'Enrollment Failed'
        DISABLED = 'DISABLED', 'Disabled'

    member = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='biometric_records',
        limit_choices_to={'role': 'MEMBER'},
    )
    biometric_type = models.CharField(
        max_length=15, choices=BiometricType.choices, default=BiometricType.FINGERPRINT
    )
    biometric_id = models.CharField(
        max_length=128,
        help_text='Device-specific biometric template ID/hash from the scanner hardware',
    )
    device_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text='Biometric scanner hardware ID that enrolled this member',
    )
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='biometric_enrollments',
    )
    status = models.CharField(
        max_length=15, choices=BiometricStatus.choices, default=BiometricStatus.ENROLLED
    )
    enrolled_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_verified_device = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'biometric_records'
        verbose_name = 'Biometric Record'
        verbose_name_plural = 'Biometric Records'
        ordering = ['member__first_name', 'member__last_name']

    def __str__(self):
        return f'{self.member.get_full_name()} — {self.get_biometric_type_display()} ({self.get_status_display()})'

    @property
    def is_verified(self):
        """Check if this member has a recent successful biometric verification."""
        return self.last_verified_at is not None

    def record_verification(self, device_id=None):
        """Mark a successful biometric check-in from a scanner device."""
        now = timezone.now()
        self.last_verified_at = now
        if device_id:
            self.last_verified_device = device_id
        self.save(update_fields=['last_verified_at', 'last_verified_device', 'updated_at'])

    def enrollment_failed(self):
        """Mark that biometric enrollment failed for this member."""
        self.status = self.BiometricStatus.FAILED
        self.save(update_fields=['status'])
