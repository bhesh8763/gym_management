"""
Trainer profile model with specializations and assigned members.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class TrainerProfile(models.Model):
    """Profile for users with role=TRAINER."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainer_profile',
    )
    specializations = models.JSONField(
        default=list,
        help_text='e.g. ["Strength Training", "Yoga", "Cardio"]'
    )
    certifications = models.JSONField(
        default=list,
        help_text='e.g. [{"name": "ACE CPT", "issued": "2023-01"}]'
    )
    experience_years = models.PositiveIntegerField(default=0)
    bio = models.TextField(blank=True)
    joined_date = models.DateField(null=True, blank=True)
    salary = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    is_available = models.BooleanField(
        default=True, help_text='Whether trainer is currently taking new members'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trainer_profiles'
        verbose_name = 'Trainer Profile'
        verbose_name_plural = 'Trainer Profiles'

    def __str__(self):
        return f'Trainer: {self.user.get_full_name()}'


class TrainerMemberAssignment(models.Model):
    """
    Tracks which trainer is assigned to which member.
    A member can have one active trainer at a time.
    """
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainer_assignments',
        limit_choices_to={'role': 'TRAINER'},
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainer_assignment',
        limit_choices_to={'role': 'MEMBER'},
    )
    assigned_date = models.DateField(auto_now_add=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'trainer_member_assignments'
        verbose_name = 'Trainer-Member Assignment'
        verbose_name_plural = 'Trainer-Member Assignments'
        ordering = ['-assigned_date']

    def __str__(self):
        return f'{self.trainer.get_full_name()} → {self.member.get_full_name()}'
