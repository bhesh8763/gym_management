"""
Workout plan management: exercise library, plans, and member assignments.
"""
from django.conf import settings
from django.db import models


class Exercise(models.Model):
    """
    Global exercise library. Trainers and owners can add exercises.
    """

    class MuscleGroup(models.TextChoices):
        CHEST = 'CHEST', 'Chest'
        BACK = 'BACK', 'Back'
        SHOULDERS = 'SHOULDERS', 'Shoulders'
        ARMS = 'ARMS', 'Arms'
        LEGS = 'LEGS', 'Legs'
        CORE = 'CORE', 'Core'
        FULL_BODY = 'FULL_BODY', 'Full Body'
        CARDIO = 'CARDIO', 'Cardio'

    class ExerciseType(models.TextChoices):
        STRENGTH = 'STRENGTH', 'Strength'
        CARDIO = 'CARDIO', 'Cardio'
        FLEXIBILITY = 'FLEXIBILITY', 'Flexibility'
        BALANCE = 'BALANCE', 'Balance'
        PLYOMETRIC = 'PLYO', 'Plyometric'

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    muscle_group = models.CharField(max_length=15, choices=MuscleGroup.choices)
    exercise_type = models.CharField(max_length=15, choices=ExerciseType.choices)
    instructions = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    image = models.ImageField(upload_to='exercises/', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercises_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exercises'
        verbose_name = 'Exercise'
        verbose_name_plural = 'Exercises'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.muscle_group})'


class WorkoutPlan(models.Model):
    """
    A named workout plan created by a trainer for a specific member.
    Contains multiple days/sessions with exercises.
    """

    class Difficulty(models.TextChoices):
        BEGINNER = 'BEGINNER', 'Beginner'
        INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
        ADVANCED = 'ADVANCED', 'Advanced'

    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='workout_plans_created',
        limit_choices_to={'role': 'TRAINER'},
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workout_plans',
        limit_choices_to={'role': 'MEMBER'},
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=15, choices=Difficulty.choices, default=Difficulty.BEGINNER
    )
    duration_weeks = models.PositiveIntegerField(default=4)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workout_plans'
        verbose_name = 'Workout Plan'
        verbose_name_plural = 'Workout Plans'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.member.get_full_name()}'


class WorkoutDay(models.Model):
    """A single day/session within a workout plan."""

    plan = models.ForeignKey(
        WorkoutPlan, on_delete=models.CASCADE, related_name='days'
    )
    day_number = models.PositiveIntegerField(help_text='e.g. Day 1, Day 2')
    day_name = models.CharField(max_length=50, blank=True, help_text='e.g. Chest Day')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workout_days'
        verbose_name = 'Workout Day'
        verbose_name_plural = 'Workout Days'
        ordering = ['day_number']
        unique_together = [('plan', 'day_number')]

    def __str__(self):
        return f'{self.plan.name} — Day {self.day_number}'


class WorkoutDayExercise(models.Model):
    """An exercise assigned to a specific day with sets/reps/rest parameters."""

    workout_day = models.ForeignKey(
        WorkoutDay, on_delete=models.CASCADE, related_name='exercises'
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name='plan_assignments'
    )
    order = models.PositiveIntegerField(default=1)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.CharField(max_length=20, blank=True, help_text='e.g. "10", "8-12", "AMRAP"')
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    rest_seconds = models.PositiveIntegerField(default=60)
    weight_kg = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workout_day_exercises'
        verbose_name = 'Workout Day Exercise'
        verbose_name_plural = 'Workout Day Exercises'
        ordering = ['order']

    def __str__(self):
        return f'{self.workout_day} — {self.exercise.name}'
