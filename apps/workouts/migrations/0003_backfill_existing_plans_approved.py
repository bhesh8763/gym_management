from django.db import migrations


def backfill_status_approved(apps, schema_editor):
    """
    Every plan created before this migration was implicitly visible to its
    member (there was no status gate). The new model default for `status`
    is DRAFT, which would hide all of them from members overnight. Mark
    everything that already exists as APPROVED so nothing regresses.
    """
    WorkoutPlan = apps.get_model('workouts', 'WorkoutPlan')
    WorkoutPlan.objects.update(status='APPROVED')


def noop_reverse(apps, schema_editor):
    # Nothing to reverse — status didn't exist before this migration chain.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('workouts', '0002_workoutplan_approved_at_workoutplan_approved_by_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_status_approved, noop_reverse),
    ]