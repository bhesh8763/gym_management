"""
Membership plans and member memberships.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class MembershipPlan(models.Model):
    """
    Defines a membership tier (e.g., Monthly Basic, Annual Premium).
    Created and managed by Owner/Staff.
    """

    class BillingCycle(models.TextChoices):
        MONTHLY = 'MONTHLY', 'Monthly'
        QUARTERLY = 'QUARTERLY', 'Quarterly (3 months)'
        HALF_YEARLY = 'HALF_YEARLY', 'Half Yearly (6 months)'
        ANNUAL = 'ANNUAL', 'Annual'
        CUSTOM = 'CUSTOM', 'Custom'

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    billing_cycle = models.CharField(
        max_length=15, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    duration_days = models.PositiveIntegerField(
        help_text='Exact duration in days (e.g., 30, 90, 365)'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    features = models.JSONField(
        default=list, blank=True,
        help_text='List of feature strings included in this plan'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'membership_plans'
        verbose_name = 'Membership Plan'
        verbose_name_plural = 'Membership Plans'
        ordering = ['price']

    def __str__(self):
        return f'{self.name} – NPR {self.price}'


class Membership(models.Model):
    """
    Links a member to a plan with start/end dates and status tracking.
    Handles renewals, freezes, and cancellations.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        EXPIRED = 'EXPIRED', 'Expired'
        FROZEN = 'FROZEN', 'Frozen'
        CANCELLED = 'CANCELLED', 'Cancelled'
        PENDING = 'PENDING', 'Pending Payment'

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
        limit_choices_to={'role': 'MEMBER'},
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name='memberships',
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    price_paid = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Actual amount paid (may differ from plan price due to offers)'
    )

    # Freeze support
    freeze_start = models.DateField(null=True, blank=True)
    freeze_end = models.DateField(null=True, blank=True)
    freeze_reason = models.TextField(blank=True)

    # Renewal chain
    renewed_from = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='renewals',
    )

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'memberships'
        verbose_name = 'Membership'
        verbose_name_plural = 'Memberships'
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.member.get_full_name()} — {self.plan.name} ({self.status})'

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE and self.end_date >= timezone.now().date()

    @property
    def days_remaining(self):
        if self.status == self.Status.ACTIVE:
            delta = self.end_date - timezone.now().date()
            return max(delta.days, 0)
        return 0
