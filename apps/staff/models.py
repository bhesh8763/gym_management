"""
Staff profile and leave request models.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class StaffProfile(models.Model):
    """Profile for users with role=STAFF."""

    class Role(models.TextChoices):
        RECEPTIONIST = 'RECEPTIONIST', 'Receptionist'
        GYM_KEEPER = 'GYM_KEEPER', 'Gym Keeper'
        TRAINER = 'TRAINER', 'Trainer'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='staff_profile',
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

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.role}'


class LeaveRequest(models.Model):
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
