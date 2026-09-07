"""
Membership plans, member memberships, and discount/offer management.
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

    # Promo code
    promo_code = models.ForeignKey(
        'PromoCode', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='memberships',
        help_text='Promo code used for this membership (if any)',
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


class FreezeRequest(models.Model):
    """
    A member-submitted request to freeze their membership.
    Staff/Owner reviews and approves or rejects it.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name='freeze_requests',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='freeze_requests',
    )
    freeze_start = models.DateField()
    freeze_end = models.DateField()
    reason = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='freeze_requests_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'freeze_requests'
        verbose_name = 'Freeze Request'
        verbose_name_plural = 'Freeze Requests'
        ordering = ['-created_at']

    def __str__(self):
        return f'Freeze request by {self.requested_by.get_full_name()} — {self.status}'


# ─── Discount / Offer Management ──────────────────────────────────────────────


class Offer(models.Model):
    """
    A discount offer that can be applied to membership plans.
    Supports percentage or fixed-amount discounts, with validity windows
    and usage limits.
    """

    class DiscountType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage (%)'
        FIXED_AMOUNT = 'FIXED_AMOUNT', 'Fixed Amount (NPR)'

    class Applicability(models.TextChoices):
        ALL_PLANS = 'ALL_PLANS', 'All Plans'
        SPECIFIC_PLANS = 'SPECIFIC_PLANS', 'Specific Plans'

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    discount_type = models.CharField(
        max_length=15, choices=DiscountType.choices, default=DiscountType.PERCENTAGE
    )
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Percentage (e.g., 20 for 20%) or fixed amount in NPR',
    )
    applicability = models.CharField(
        max_length=15, choices=Applicability.choices, default=Applicability.ALL_PLANS
    )
    plans = models.ManyToManyField(
        MembershipPlan, blank=True, related_name='offers',
        help_text='Applicable plans (when applicability is SPECIFIC_PLANS)',
    )
    max_uses = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Maximum total uses across all members (null = unlimited)',
    )
    max_uses_per_member = models.PositiveIntegerField(
        default=1,
        help_text='Maximum times a single member can use this offer',
    )
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'offers'
        verbose_name = 'Offer'
        verbose_name_plural = 'Offers'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_discount_type_display()}: {self.discount_value})'

    @property
    def is_valid(self):
        """Check if the offer is currently valid (active + within date range)."""
        now = timezone.now()
        return (
            self.is_active
            and self.valid_from <= now <= self.valid_until
        )

    @property
    def total_uses(self):
        return self.promo_codes.aggregate(
            total=models.Sum('used_count')
        )['total'] or 0

    def is_available(self):
        """Check if the offer can still be used (not exhausted)."""
        if not self.is_valid:
            return False
        if self.max_uses is not None and self.total_uses >= self.max_uses:
            return False
        return True

    def calculate_discount(self, original_price):
        """Calculate the discount amount for a given original price."""
        if self.discount_type == self.DiscountType.PERCENTAGE:
            return original_price * (self.discount_value / Decimal('100'))
        else:
            return min(self.discount_value, original_price)

    def applies_to_plan(self, plan):
        """Check if this offer applies to the given plan."""
        if self.applicability == self.Applicability.ALL_PLANS:
            return True
        return self.plans.filter(pk=plan.pk).exists()


class PromoCode(models.Model):
    """
    A unique redemption code linked to an Offer.
    Members enter this code during membership purchase to get the discount.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        EXPIRED = 'EXPIRED', 'Expired'
        EXHAUSTED = 'EXHAUSTED', 'Exhausted'
        DISABLED = 'DISABLED', 'Disabled'

    code = models.CharField(max_length=50, unique=True)
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='promo_codes')
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    max_uses = models.PositiveIntegerField(
        default=1, help_text='Max times this specific code can be redeemed'
    )
    used_count = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='promo_codes_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'promo_codes'
        verbose_name = 'Promo Code'
        verbose_name_plural = 'Promo Codes'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} — {self.offer.name} ({self.status})'

    @property
    def is_valid(self):
        """Check if this promo code can be redeemed."""
        now = timezone.now()
        if self.status != self.Status.ACTIVE:
            return False
        if not (self.valid_from <= now <= self.valid_until):
            return False
        if self.used_count >= self.max_uses:
            return False
        if not self.offer.is_available():
            return False
        return True

    def redeem(self):
        """Mark one use of this promo code."""
        self.used_count += 1
        if self.used_count >= self.max_uses:
            self.status = self.Status.EXHAUSTED
        self.save(update_fields=['used_count', 'status', 'updated_at'])

    def calculate_discount(self, original_price):
        """Delegate to the parent offer."""
        return self.offer.calculate_discount(original_price)


class PromoCodeUsage(models.Model):
    """
    Records each time a promo code is redeemed, storing the price breakdown
    for audit and reporting.
    """

    promo_code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name='usages')
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='promo_code_usages',
        limit_choices_to={'role': 'MEMBER'},
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='promo_code_usage',
    )
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_applied = models.DecimalField(max_digits=10, decimal_places=2)
    final_price = models.DecimalField(max_digits=10, decimal_places=2)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'promo_code_usages'
        verbose_name = 'Promo Code Usage'
        verbose_name_plural = 'Promo Code Usages'
        ordering = ['-used_at']

    def __str__(self):
        return f'{self.member.get_full_name()} used {self.promo_code.code} — saved NPR {self.discount_applied}'
