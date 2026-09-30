from django.db import migrations


TENANT_MODELS = [
    ('members', 'MemberProfile'),
    ('staff', 'StaffProfile'),
    ('staff', 'LeaveRequest'),
    ('trainers', 'TrainerProfile'),
    ('trainers', 'TrainerMemberAssignment'),
    ('memberships', 'MembershipPlan'),
    ('memberships', 'Membership'),
    ('memberships', 'FreezeRequest'),
    ('memberships', 'Offer'),
    ('memberships', 'PromoCode'),
    ('memberships', 'PromoCodeUsage'),
    ('attendance', 'Attendance'),
    ('attendance', 'QRAttendanceToken'),
    ('attendance', 'BiometricRecord'),
    ('payments', 'Payment'),
    ('workouts', 'WorkoutTemplate'),
    ('workouts', 'WorkoutAssignment'),
    ('workouts', 'WorkoutCompletionLog'),
    ('diet', 'DietPlan'),
    ('diet', 'MealLog'),
    ('progress', 'ProgressEntry'),
    ('progress', 'PersonalRecord'),
    ('lockers', 'Locker'),
    ('lockers', 'LockerAssignment'),
    ('equipment', 'Equipment'),
    ('equipment', 'MaintenanceRecord'),
    ('notifications', 'Notification'),
    ('notifications', 'MessageGroup'),
    ('notifications', 'GroupMessage'),
    ('notifications', 'PinnedConversation'),
]


def backfill_branch_access(apps, schema_editor):
    Gym = apps.get_model('gyms', 'Gym')
    GymMembership = apps.get_model('gyms', 'GymMembership')
    BranchMembership = apps.get_model('gyms', 'BranchMembership')

    for gym in Gym.objects.all():
        branch = gym.branches.filter(is_primary=True).first() or gym.branches.first()
        if branch is None:
            continue

        for membership in GymMembership.objects.filter(gym_id=gym.id):
            BranchMembership.objects.get_or_create(
                gym_membership_id=membership.id,
                branch_id=branch.id,
                defaults={'can_manage': membership.role in ('OWNER', 'STAFF')},
            )

        for app_label, model_name in TENANT_MODELS:
            model = apps.get_model(app_label, model_name)
            model.objects.filter(gym_id=gym.id, branch_id__isnull=True).update(
                branch_id=branch.id,
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('gyms', '0002_backfill_tenancy'),
    ]

    operations = [
        migrations.RunPython(backfill_branch_access, noop),
    ]
