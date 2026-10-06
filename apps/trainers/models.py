"""
Trainer profile model with specializations and assigned members.
"""
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.gyms.models import TenantScopedModel


class TrainerProfile(TenantScopedModel):
    """Profile for users with role=TRAINER."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainer_profiles',
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
        constraints = [
            models.UniqueConstraint(fields=['gym', 'user'], name='unique_trainer_profile_per_gym'),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(gym__isnull=True),
                name='unique_legacy_trainer_profile_user',
            ),
        ]

    def __str__(self):
        return f'Trainer: {self.user.get_full_name()}'

    def revive(self):
        """Undo the deactivation done when this profile went to Trash.

        Deleting a trainer deactivates their gym membership; ``restore()``
        only clears the soft-delete markers, so without this the trainer would
        come back unable to work in the gym. Called by Trash restore.
        """
        from apps.gyms.models import GymMembership
        user = self.user
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        if self.gym_id:
            GymMembership.objects.filter(
                user=user,
                gym_id=self.gym_id,
                role=GymMembership.Role.TRAINER,
                status=GymMembership.Status.INACTIVE,
            ).update(status=GymMembership.Status.ACTIVE)
        return user


class TrainerMemberAssignment(TenantScopedModel):
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
