"""
Diet and nutrition plan models.
"""
from django.conf import settings
from django.db import models


class DietPlan(models.Model):
    """
    A nutrition plan created by a trainer for a specific member.
    """

    class Goal(models.TextChoices):
        WEIGHT_LOSS = 'WEIGHT_LOSS', 'Weight Loss'
        MUSCLE_GAIN = 'MUSCLE_GAIN', 'Muscle Gain'
        MAINTENANCE = 'MAINTENANCE', 'Maintenance'
        ENDURANCE = 'ENDURANCE', 'Endurance'

    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='diet_plans_created',
        limit_choices_to={'role': 'TRAINER'},
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='diet_plans',
        limit_choices_to={'role': 'MEMBER'},
    )
    name = models.CharField(max_length=150)
    goal = models.CharField(max_length=15, choices=Goal.choices, blank=True)
    daily_calories = models.PositiveIntegerField(null=True, blank=True)
    protein_grams = models.PositiveIntegerField(null=True, blank=True)
    carbs_grams = models.PositiveIntegerField(null=True, blank=True)
    fat_grams = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'diet_plans'
        verbose_name = 'Diet Plan'
        verbose_name_plural = 'Diet Plans'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.member.get_full_name()}'


class Meal(models.Model):
    """A single meal within a diet plan."""

    class MealType(models.TextChoices):
        BREAKFAST = 'BREAKFAST', 'Breakfast'
        MORNING_SNACK = 'MORNING_SNACK', 'Morning Snack'
        LUNCH = 'LUNCH', 'Lunch'
        AFTERNOON_SNACK = 'AFTERNOON_SNACK', 'Afternoon Snack'
        DINNER = 'DINNER', 'Dinner'
        POST_WORKOUT = 'POST_WORKOUT', 'Post Workout'
        PRE_WORKOUT = 'PRE_WORKOUT', 'Pre Workout'

    diet_plan = models.ForeignKey(
        DietPlan, on_delete=models.CASCADE, related_name='meals'
    )
    meal_type = models.CharField(max_length=20, choices=MealType.choices)
    time_suggestion = models.TimeField(null=True, blank=True)
    food_items = models.JSONField(
        default=list,
        help_text='List of food items, e.g. [{"name": "Oats", "amount": "100g", "calories": 370}]'
    )
    total_calories = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'meals'
        verbose_name = 'Meal'
        verbose_name_plural = 'Meals'
        ordering = ['meal_type']

    def __str__(self):
        return f'{self.diet_plan.name} — {self.meal_type}'
    
class MealLog(models.Model):
    """
    A member's actual daily food intake log — separate from the prescribed
    DietPlan/Meal, which represents what the trainer recommends.
    """
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='meal_logs',
        limit_choices_to={'role': 'MEMBER'},
    )
    date = models.DateField()
    food_items = models.JSONField(
        default=list,
        help_text='List of food items, e.g. [{"name": "Rice", "amount": "150g", "calories": 200}]'
    )
    total_calories = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'meal_logs'
        verbose_name = 'Meal Log'
        verbose_name_plural = 'Meal Logs'
        ordering = ['-date']

    def __str__(self):
        return f'{self.member.get_full_name()} — {self.date}'

    def save(self, *args, **kwargs):
        self.total_calories = sum(item.get('calories', 0) for item in self.food_items)
        super().save(*args, **kwargs)