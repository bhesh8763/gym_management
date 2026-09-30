from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('workouts', '0005_migrate_legacy_assignments'),
    ]

    operations = [
        migrations.RemoveField(model_name='workouttemplate', name='member'),
        migrations.RemoveField(model_name='workouttemplate', name='is_active'),
        migrations.RemoveField(model_name='workouttemplate', name='start_date'),
        migrations.RemoveField(model_name='workouttemplate', name='end_date'),
        # DeleteModel drops the table and every field on it in one step —
        # don't RemoveField each column first, that strips the model's
        # state before DeleteModel runs and breaks reversing this migration.
        migrations.DeleteModel(name='WorkoutPlanAssignment'),
    ]