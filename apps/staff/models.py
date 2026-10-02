"""
Staff profile, leave request, and shift scheduling models.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.gyms.models import TenantScopedModel


class StaffProfile(TenantScopedModel):
    """Profile for users with role=STAFF."""

    class Role(models.TextChoices):
        RECEPTIONIST = 'RECEPTIONIST', 'Receptionist'
        GYM_KEEPER = 'GYM_KEEPER', 'Gym Keeper'
        TRAINER = 'TRAINER', 'Trainer'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profiles',
    )
    role = models.CharField(
        max_length=15, choices=Role.choices, default=Role.RECEPTIONIST
    )
    joined_date = models.DateField(null=True, blank=True)
    salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, blank=True)
    marital_status = models.CharField(max_length=15, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    id_document = models.FileField(
        upload_to='staff/documents/', null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'staff_profiles'
        verbose_name = 'Staff Profile'
        verbose_name_plural = 'Staff Profiles'
        constraints = [
            models.UniqueConstraint(fields=['gym', 'user'], name='unique_staff_profile_per_gym'),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(gym__isnull=True),
                name='unique_legacy_staff_profile_user',
            ),
        ]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.role}'


class LeaveRequest(TenantScopedModel):
    """Leave requests submitted by staff or trainers."""

    class LeaveType(models.TextChoices):
        SICK = 'SICK', 'Sick Leave'
        CASUAL = 'CASUAL', 'Casual Leave'
        ANNUAL = 'ANNUAL', 'Annual Leave'
        UNPAID = 'UNPAID', 'Unpaid Leave'
        OTHER = 'OTHER', 'Other'

    class LeaveStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leave_requests',
    )
    leave_type = models.CharField(max_length=10, choices=LeaveType.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(
        max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='leave_reviews',
    )
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leave_requests'
        verbose_name = 'Leave Request'
        verbose_name_plural = 'Leave Requests'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.requester.get_full_name()} — {self.leave_type} ({self.status})'

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1


class Shift(models.Model):
    """Fixed shift time template (e.g. Morning 05:00–10:00)."""

    name = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'shifts'
        verbose_name = 'Shift'
        verbose_name_plural = 'Shifts'
        ordering = ['start_time', 'name']

    def __str__(self):
        return f'{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})'


class StaffShift(models.Model):
    """Weekly shift assignment: one staff member may hold multiple
    non-overlapping shifts on the same weekday."""

    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_shifts',
        limit_choices_to={'role__in': ['STAFF', 'TRAINER']},
    )
    shift = models.ForeignKey(
        Shift,
        on_delete=models.CASCADE,
        related_name='staff_shifts',
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'staff_shifts'
        verbose_name = 'Staff Shift'
        verbose_name_plural = 'Staff Shifts'
        ordering = ['weekday', 'shift__start_time', 'staff__last_name']
        constraints = [
            models.UniqueConstraint(
                fields=['staff', 'shift', 'weekday'],
                name='unique_staff_shift_per_weekday',
            ),
        ]

    def __str__(self):
        return (
            f'{self.staff.get_full_name()} — {self.get_weekday_display()} '
            f'{self.shift.name}'
        )
