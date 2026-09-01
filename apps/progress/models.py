"""
Progress tracking: body metrics and personal records (PRs).
"""
from django.conf import settings
from django.db import models


class ProgressEntry(models.Model):
    """
    A snapshot of a member's body metrics on a given date.
    Tracked over time to show improvement.
    """
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='progress_entries',
        limit_choices_to={'role': 'MEMBER'},
    )
    date = models.DateField()
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    height_cm = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    body_fat_percentage = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )
    muscle_mass_kg = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    # Body measurements in cm
    chest_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    waist_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hips_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    bicep_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    thigh_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='progress_recorded',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'progress_entries'
        verbose_name = 'Progress Entry'
        verbose_name_plural = 'Progress Entries'
        ordering = ['-date']
        unique_together = [('member', 'date')]

    def __str__(self):
        return f'{self.member.get_full_name()} — {self.date}'

    @property
    def bmi(self):
        if self.weight_kg and self.height_cm:
            h_m = float(self.height_cm) / 100
            return round(float(self.weight_kg) / (h_m ** 2), 2)
        return None


class PersonalRecord(models.Model):
    """
    Tracks a member's best performance on a specific exercise (PR).
    e.g. Bench Press 1RM = 100kg
    """
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='personal_records',
        limit_choices_to={'role': 'MEMBER'},
    )
    exercise = models.ForeignKey(
        'workouts.Exercise',
        on_delete=models.CASCADE,
        related_name='personal_records',
    )
    date = models.DateField()
    value = models.DecimalField(
        max_digits=8, decimal_places=2,
        help_text='e.g. weight in kg, distance in km, time in seconds'
    )
    unit = models.CharField(
        max_length=20, default='kg',
        help_text='Unit for the value (kg, km, seconds, reps, etc.)'
    )
    best_weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    best_reps = models.PositiveIntegerField(null=True, blank=True)
    best_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    assignment = models.ForeignKey(
        'workouts.WorkoutAssignment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='personal_records',
    )
    log = models.ForeignKey(
        'workouts.WorkoutCompletionLog', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='personal_records',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'personal_records'
        verbose_name = 'Personal Record'
        verbose_name_plural = 'Personal Records'
        ordering = ['-date']

    def __str__(self):
        return f'{self.member.get_full_name()} — {self.exercise.name}: {self.value} {self.unit}'
