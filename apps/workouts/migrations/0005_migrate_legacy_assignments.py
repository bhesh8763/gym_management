from django.db import migrations


def forwards(apps, schema_editor):
    WorkoutTemplate = apps.get_model('workouts', 'WorkoutTemplate')
    WorkoutAssignment = apps.get_model('workouts', 'WorkoutAssignment')
    WorkoutPlanAssignment = apps.get_model('workouts', 'WorkoutPlanAssignment')

    # 1. Legacy single-member field on the template itself.
    for template in WorkoutTemplate.objects.all():
        if template.member_id:
            WorkoutAssignment.objects.get_or_create(
                template=template,
                member_id=template.member_id,
                defaults=dict(
                    assigned_by_id=template.trainer_id,
                    status='ACTIVE' if template.is_active else 'PAUSED',
                    start_date=template.start_date or template.created_at.date(),
                    end_date=template.end_date,
                ),
            )

    # 2. Explicit assignments already made through WorkoutPlanAssignment.
    for row in WorkoutPlanAssignment.objects.all():
        WorkoutAssignment.objects.get_or_create(
            template_id=row.plan_id,
            member_id=row.member_id,
            defaults=dict(
                assigned_by_id=row.assigned_by_id,
                status='ACTIVE',
                start_date=row.assigned_at.date(),
            ),
        )


def backwards(apps, schema_editor):
    WorkoutAssignment = apps.get_model('workouts', 'WorkoutAssignment')
    WorkoutAssignment.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('workouts', '0004_reconcile_template_and_assignment'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]