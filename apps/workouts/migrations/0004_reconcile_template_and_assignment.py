import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def remap_pending_to_in_review(apps, schema_editor):
    """Teammate's status field used PENDING; the redesign renames that
    state to IN_REVIEW. Same meaning, just aligning the label."""
    WorkoutTemplate = apps.get_model('workouts', 'WorkoutTemplate')
    WorkoutTemplate.objects.filter(status='PENDING').update(status='IN_REVIEW')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('workouts', '0003_backfill_existing_plans_approved'),
    ]

    operations = [
        # --- rename plan -> template throughout (unchanged from original plan) ---
        migrations.RenameModel(old_name='WorkoutPlan', new_name='WorkoutTemplate'),
        migrations.AlterModelTable(name='workouttemplate', table='workout_templates'),
        migrations.RenameField(model_name='workoutday', old_name='plan', new_name='template'),
        migrations.AlterUniqueTogether(name='workoutday', unique_together=set()),

        # --- Exercise: library fields the doc called for ---
        migrations.AddField(
            model_name='exercise', name='equipment',
            field=models.CharField(blank=True, help_text='e.g. Barbell, Dumbbell, Bodyweight', max_length=100),
        ),
        migrations.AddField(
            model_name='exercise', name='common_mistakes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='exercise', name='alternative_exercises',
            field=models.ManyToManyField(
                blank=True, help_text='Swappable substitutes shown when a member cannot perform this exercise.',
                to='workouts.exercise',
            ),
        ),

        # --- WorkoutTemplate: goal + reconcile approval fields ---
        migrations.AddField(
            model_name='workouttemplate', name='goal',
            field=models.CharField(blank=True, help_text='e.g. Fat Loss, Hypertrophy, Strength, Mobility', max_length=100),
        ),
        migrations.AlterField(
            model_name='workouttemplate', name='status',
            field=models.CharField(
                choices=[('DRAFT', 'Draft'), ('IN_REVIEW', 'In review'), ('APPROVED', 'Approved'), ('ARCHIVED', 'Archived')],
                default='DRAFT', help_text='Draft \u2192 In review \u2192 Approved \u2192 Archived', max_length=15,
            ),
        ),
        migrations.RunPython(remap_pending_to_in_review, noop_reverse),
        migrations.AddField(
            model_name='workouttemplate', name='reviewed_by',
            field=models.ForeignKey(
                blank=True, limit_choices_to={'role__in': ['OWNER', 'STAFF']}, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='workout_templates_reviewed', to=settings.AUTH_USER_MODEL,
            ),
        ),
        # approved_at / approved_by are dropped: the backfill migration only ever
        # set `status`, never these two, so every existing row has them NULL —
        # nothing to lose. `reviewed_by` replaces `approved_by` going forward.
        migrations.RemoveField(model_name='workouttemplate', name='approved_at'),
        migrations.RemoveField(model_name='workouttemplate', name='approved_by'),
        migrations.AlterField(
            model_name='workouttemplate', name='trainer',
            field=models.ForeignKey(
                limit_choices_to={'role': 'TRAINER'}, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='workout_templates_created', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterModelOptions(
            name='workouttemplate',
            options={'ordering': ['-updated_at'], 'verbose_name': 'Workout Template', 'verbose_name_plural': 'Workout Templates'},
        ),

        # --- WorkoutDay: weeks ---
        migrations.AddField(
            model_name='workoutday', name='week_number',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='workoutday', name='day_name',
            field=models.CharField(blank=True, help_text='e.g. Push Day', max_length=50),
        ),
        migrations.AlterField(
            model_name='workoutday', name='template',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='days', to='workouts.workouttemplate'),
        ),
        migrations.AlterUniqueTogether(
            name='workoutday', unique_together={('template', 'week_number', 'day_number')},
        ),
        migrations.AlterModelOptions(
            name='workoutday', options={'ordering': ['week_number', 'day_number'], 'verbose_name': 'Workout Day', 'verbose_name_plural': 'Workout Days'},
        ),

        # --- WorkoutDayExercise: tempo / RPE, related_name fix ---
        migrations.AddField(
            model_name='workoutdayexercise', name='tempo',
            field=models.CharField(blank=True, help_text='e.g. "2-0-2" (eccentric-pause-concentric)', max_length=15),
        ),
        migrations.AddField(
            model_name='workoutdayexercise', name='rpe',
            field=models.PositiveSmallIntegerField(blank=True, help_text='Rate of Perceived Exertion, 1-10', null=True),
        ),
        migrations.AlterField(
            model_name='workoutdayexercise', name='duration_seconds',
            field=models.PositiveIntegerField(blank=True, help_text='For timed exercises (e.g. plank)', null=True),
        ),
        migrations.AlterField(
            model_name='workoutdayexercise', name='reps',
            field=models.CharField(blank=True, help_text='e.g. "10", "8-12", "AMRAP", "Failure"', max_length=20),
        ),
        migrations.AlterField(
            model_name='workoutdayexercise', name='exercise',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='day_placements', to='workouts.exercise'),
        ),

        # --- new: WorkoutAssignment (replaces WorkoutPlanAssignment, added below in 0006
        #     once its data has been copied across in 0005) ---
        migrations.CreateModel(
            name='WorkoutAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('ACTIVE', 'Active'), ('PAUSED', 'Paused'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], default='ACTIVE', max_length=15)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField(blank=True, help_text='Auto-filled from template duration if left blank', null=True)),
                ('goal_note', models.CharField(blank=True, help_text='e.g. "prep for tournament"', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_by', models.ForeignKey(limit_choices_to={'role__in': ['TRAINER', 'OWNER', 'STAFF']}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='workout_assignments_made', to=settings.AUTH_USER_MODEL)),
                ('member', models.ForeignKey(limit_choices_to={'role': 'MEMBER'}, on_delete=django.db.models.deletion.CASCADE, related_name='workout_assignments', to=settings.AUTH_USER_MODEL)),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='workouts.workouttemplate')),
            ],
            options={
                'verbose_name': 'Workout Assignment',
                'verbose_name_plural': 'Workout Assignments',
                'db_table': 'workout_assignments',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='workoutassignment',
            constraint=models.UniqueConstraint(condition=models.Q(('status', 'ACTIVE')), fields=('template', 'member'), name='one_active_assignment_per_member_per_template'),
        ),

        # --- new: WorkoutCompletionLog ---
        migrations.CreateModel(
            name='WorkoutCompletionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('status', models.CharField(choices=[('COMPLETED', 'Completed'), ('SKIPPED', 'Skipped'), ('PARTIAL', 'Partial')], default='COMPLETED', max_length=15)),
                ('duration_minutes', models.PositiveIntegerField(blank=True, null=True)),
                ('calories', models.PositiveIntegerField(blank=True, null=True)),
                ('perceived_difficulty', models.PositiveSmallIntegerField(blank=True, help_text='1-10', null=True)),
                ('pain_level', models.PositiveSmallIntegerField(blank=True, help_text='0-10, 0 = none', null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='workouts.workoutassignment')),
                ('workout_day', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='completion_logs', to='workouts.workoutday')),
            ],
            options={
                'verbose_name': 'Workout Completion Log',
                'verbose_name_plural': 'Workout Completion Logs',
                'db_table': 'workout_completion_logs',
                'ordering': ['-date'],
                'unique_together': {('assignment', 'workout_day', 'date')},
            },
        ),
    ]