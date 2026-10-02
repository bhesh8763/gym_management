from datetime import time

from django.db import migrations

DEFAULT_SHIFTS = [
    ('Morning', time(5, 0), time(10, 0)),
    ('Day', time(10, 0), time(16, 0)),
    ('Evening', time(16, 0), time(20, 0)),
    ('Night', time(20, 0), time(22, 0)),
]


def seed_default_shifts(apps, schema_editor):
    """Seed the four fixed shift templates the gym schedules against.

    get_or_create keeps the migration idempotent if an admin already
    created one of these by hand.
    """
    Shift = apps.get_model('staff', 'Shift')
    for name, start_time, end_time in DEFAULT_SHIFTS:
        Shift.objects.get_or_create(
            name=name,
            defaults={'start_time': start_time, 'end_time': end_time},
        )


def remove_default_shifts(apps, schema_editor):
    Shift = apps.get_model('staff', 'Shift')
    Shift.objects.filter(name__in=[name for name, _, _ in DEFAULT_SHIFTS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('staff', '0010_shift_staffshift'),
    ]

    operations = [
        migrations.RunPython(seed_default_shifts, remove_default_shifts),
    ]
