"""
Migration 0003: Upgrade diet module schema.

DietPlan changes:
  - Rename trainer → created_by (drop limit_choices_to restriction)
  - Rename protein_grams → protein_g
  - Rename carbs_grams   → carbs_g
  - Rename fat_grams     → fats_g
  - Add RECOMPOSITION to goal choices

Meal changes:
  - Remove food_items (JSONField)
  - Remove total_calories
  - Add food_name (CharField, default '' for existing rows)
  - Add portion   (CharField, blank)
  - Add calories  (PositiveIntegerField, null/blank)
  - Update meal_type choices (add MID_MORNING / EVENING_SNACK, rename labels)
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('diet', '0002_meallog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── DietPlan: rename trainer → created_by ─────────────────────────────
        migrations.RenameField(
            model_name='dietplan',
            old_name='trainer',
            new_name='created_by',
        ),
        # Drop the TRAINER-only limit_choices_to on the new created_by field
        migrations.AlterField(
            model_name='dietplan',
            name='created_by',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='diet_plans_created',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # ── DietPlan: rename macro fields ─────────────────────────────────────
        migrations.RenameField(
            model_name='dietplan',
            old_name='protein_grams',
            new_name='protein_g',
        ),
        migrations.RenameField(
            model_name='dietplan',
            old_name='carbs_grams',
            new_name='carbs_g',
        ),
        migrations.RenameField(
            model_name='dietplan',
            old_name='fat_grams',
            new_name='fats_g',
        ),

        # ── DietPlan: update goal choices (add RECOMPOSITION) ─────────────────
        migrations.AlterField(
            model_name='dietplan',
            name='goal',
            field=models.CharField(
                blank=True,
                choices=[
                    ('WEIGHT_LOSS',   'Weight Loss'),
                    ('MUSCLE_GAIN',   'Muscle Gain'),
                    ('RECOMPOSITION', 'Recomposition'),
                    ('MAINTENANCE',   'Maintenance'),
                    ('ENDURANCE',     'Endurance'),
                ],
                max_length=15,
            ),
        ),

        # ── Meal: remove old JSONField columns ────────────────────────────────
        migrations.RemoveField(model_name='meal', name='food_items'),
        migrations.RemoveField(model_name='meal', name='total_calories'),

        # ── Meal: add new flat columns ────────────────────────────────────────
        migrations.AddField(
            model_name='meal',
            name='food_name',
            field=models.CharField(default='', max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='meal',
            name='portion',
            field=models.CharField(
                blank=True,
                help_text='e.g. 100g, 1 cup, 2 slices',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='meal',
            name='calories',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),

        # ── Meal: update meal_type choices ────────────────────────────────────
        migrations.AlterField(
            model_name='meal',
            name='meal_type',
            field=models.CharField(
                choices=[
                    ('BREAKFAST',     'Breakfast'),
                    ('MID_MORNING',   'Mid-Morning'),
                    ('LUNCH',         'Lunch'),
                    ('PRE_WORKOUT',   'Pre-Workout'),
                    ('POST_WORKOUT',  'Post-Workout'),
                    ('DINNER',        'Dinner'),
                    ('EVENING_SNACK', 'Evening Snack'),
                ],
                max_length=20,
            ),
        ),
    ]
