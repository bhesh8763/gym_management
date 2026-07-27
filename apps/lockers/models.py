"""
Locker management: locker inventory and assignments to members.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Locker(models.Model):
    """Represents a physical locker in the gym."""

    class LockerStatus(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        OCCUPIED = 'OCCUPIED', 'Occupied'
        MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'
        RESERVED = 'RESERVED', 'Reserved'

    locker_number = models.CharField(max_length=20, unique=True)
    location = models.CharField(
        max_length=100, blank=True,
        help_text='e.g. "Men\'s Block A", "Women\'s Block B"'
    )
    status = models.CharField(
        max_length=15,
        choices=LockerStatus.choices,
        default=LockerStatus.AVAILABLE,
        db_index=True,
    )
    monthly_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Fee per month for locker rental'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lockers'
        verbose_name = 'Locker'
        verbose_name_plural = 'Lockers'
        ordering = ['locker_number']

    def __str__(self):
        return f'Locker {self.locker_number} ({self.status})'


class LockerAssignment(models.Model):
    """Records which member is assigned to which locker and for how long."""

    locker = models.ForeignKey(
        Locker, on_delete=models.CASCADE, related_name='assignments'
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='locker_assignments',
        limit_choices_to={'role': 'MEMBER'},
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='locker_assignments_made',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'locker_assignments'
        verbose_name = 'Locker Assignment'
        verbose_name_plural = 'Locker Assignments'
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.locker} → {self.member.get_full_name()}'
