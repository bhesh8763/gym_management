"""
Equipment inventory and maintenance schedule management.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Equipment(models.Model):
    """Gym equipment inventory item."""

    class Condition(models.TextChoices):
        EXCELLENT = 'EXCELLENT', 'Excellent'
        GOOD = 'GOOD', 'Good'
        FAIR = 'FAIR', 'Fair'
        POOR = 'POOR', 'Poor'
        OUT_OF_SERVICE = 'OUT_OF_SERVICE', 'Out of Service'

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True, help_text='e.g. Cardio, Free Weights')
    brand = models.CharField(max_length=100, blank=True)
    model_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, null=True, blank=True, unique=True)
    quantity = models.PositiveIntegerField(default=1)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    condition = models.CharField(
        max_length=15,
        choices=Condition.choices,
        default=Condition.GOOD,
        db_index=True,
    )
    location = models.CharField(max_length=100, blank=True, help_text='Where in the gym')
    image = models.ImageField(upload_to='equipment/', null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'equipment'
        verbose_name = 'Equipment'
        verbose_name_plural = 'Equipment'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.quantity}x)'


class MaintenanceRecord(models.Model):
    """
    Tracks maintenance events for a piece of equipment.
    Supports scheduled (future) and completed maintenance.
    """

    class MaintenanceType(models.TextChoices):
        ROUTINE = 'ROUTINE', 'Routine Check'
        REPAIR = 'REPAIR', 'Repair'
        REPLACEMENT = 'REPLACEMENT', 'Part Replacement'
        INSPECTION = 'INSPECTION', 'Inspection'

    class MaintenanceStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, related_name='maintenance_records'
    )
    maintenance_type = models.CharField(
        max_length=15, choices=MaintenanceType.choices
    )
    status = models.CharField(
        max_length=15,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.SCHEDULED,
    )
    scheduled_date = models.DateField()
    completed_date = models.DateField(null=True, blank=True)
    performed_by = models.CharField(
        max_length=150, blank=True,
        help_text='Technician or person who performed maintenance'
    )
    cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    description = models.TextField(blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='maintenance_recorded',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'maintenance_records'
        verbose_name = 'Maintenance Record'
        verbose_name_plural = 'Maintenance Records'
        ordering = ['-scheduled_date']

    def __str__(self):
        return f'{self.equipment.name} — {self.maintenance_type} ({self.scheduled_date})'
