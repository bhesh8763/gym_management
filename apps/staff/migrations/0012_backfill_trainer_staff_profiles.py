from django.db import migrations


def backfill_trainer_staff_profiles(apps, schema_editor):
    """Give every live TrainerProfile user a matching StaffProfile.

    The staff directory lists StaffProfile rows, but the demo seed (and the
    API-only POST /trainers/profiles/ path) created TrainerProfile rows alone,
    so those trainers never appeared in the directory. This backfills one
    StaffProfile (role TRAINER) per TrainerProfile for the same user+gym.

    Idempotent — get_or_create on the (user, gym) unique pair — and skips
    soft-deleted trainer rows so trash doesn't get resurrected.
    """
    TrainerProfile = apps.get_model('trainers', 'TrainerProfile')
    StaffProfile = apps.get_model('staff', 'StaffProfile')

    for tp in TrainerProfile.objects.filter(deleted_at__isnull=True).select_related('user'):
        StaffProfile.objects.get_or_create(
            user=tp.user,
            gym=tp.gym,
            defaults={
                'branch': tp.branch,
                'role': 'TRAINER',
                'joined_date': tp.joined_date or tp.created_at.date(),
                'salary': tp.salary,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('staff', '0011_seed_default_shifts'),
        ('trainers', '0006_softdelete_and_roles'),
    ]

    operations = [
        # Reverse is a no-op on purpose: rolling back must not delete
        # StaffProfiles that may since have been edited or created by hand.
        migrations.RunPython(backfill_trainer_staff_profiles, migrations.RunPython.noop),
    ]
