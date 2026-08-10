"""
Payment and transaction models.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Payment(models.Model):
    """
    Records a payment transaction for a membership or any other service.
    """

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        ESEWA = 'ESEWA', 'eSewa'
        KHALTI = 'KHALTI', 'Khalti'
        BANK_TRANSFER = 'BANK', 'Bank Transfer'
        CARD = 'CARD', 'Card'
        OTHER = 'OTHER', 'Other'

    class PaymentStatus(models.TextChoices):
        PAID = 'PAID', 'Paid'
        PENDING = 'PENDING', 'Pending'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'
        PARTIAL = 'PARTIAL', 'Partially Paid'

    class PaymentFor(models.TextChoices):
        MEMBERSHIP = 'MEMBERSHIP', 'Membership'
        LOCKER = 'LOCKER', 'Locker'
        PERSONAL_TRAINING = 'PT', 'Personal Training'
        OTHER = 'OTHER', 'Other'

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments',
        limit_choices_to={'role': 'MEMBER'},
    )
    membership = models.ForeignKey(
        'memberships.Membership',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payments',
    )
    payment_for = models.CharField(
        max_length=12, choices=PaymentFor.choices, default=PaymentFor.MEMBERSHIP
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text='Actual amount received (amount - discount)'
    )
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    transaction_id = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=50, unique=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payments_collected',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-created_at']

    def __str__(self):
        return f'#{self.receipt_number} — {self.member.get_full_name()} — NPR {self.amount_paid}'

    def save(self, *args, **kwargs):
        # Only PAID/PARTIAL payments have actually received money.
        # PENDING/FAILED/REFUNDED should not show a collected amount.
        if self.status in (self.PaymentStatus.PAID, self.PaymentStatus.PARTIAL):
            self.amount_paid = self.amount - self.discount
        else:
            self.amount_paid = Decimal('0')
        super().save(*args, **kwargs)
