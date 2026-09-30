from django.db import migrations


def backfill_tenancy(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    Gym = apps.get_model('gyms', 'Gym')
    Branch = apps.get_model('gyms', 'Branch')
    GymMembership = apps.get_model('gyms', 'GymMembership')
    PlanSubscription = apps.get_model('accounts', 'PlanSubscription')

    owners = list(User.objects.filter(role='OWNER').order_by('id'))
    gyms_by_owner = {}
    for index, owner in enumerate(owners, start=1):
        gym = Gym.objects.create(
            owner_id=owner.id,
            name=f'{owner.first_name} {owner.last_name} Gym'.strip() or f'FitCore Gym {index}',
            public_id=f'GY-LEG{index:03d}',
            slug=f'legacy-gym-{index}',
            status='ACTIVE',
            onboarding_complete=True,
        )
        Branch.objects.create(
            gym_id=gym.id,
            name='Main Branch',
            code='MAIN',
            is_primary=True,
            status='ACTIVE',
        )
        gyms_by_owner[owner.id] = gym

    fallback_gym = next(iter(gyms_by_owner.values()), None)
    if fallback_gym is None:
        fallback_gym = Gym.objects.create(
            owner=None,
            name='Legacy FitCore Gym',
            public_id='GY-LEG000',
            slug='legacy-fitcore-gym',
            status='ACTIVE',
            onboarding_complete=True,
        )
        Branch.objects.create(
            gym_id=fallback_gym.id,
            name='Main Branch',
            code='MAIN',
            is_primary=True,
            status='ACTIVE',
        )

    role_map = {
        'OWNER': 'OWNER',
        'STAFF': 'STAFF',
        'TRAINER': 'TRAINER',
        'MEMBER': 'MEMBER',
        'ADMIN': 'STAFF',
    }
    membership_gym_by_user = {}
    for user in User.objects.all().order_by('id'):
        gym = gyms_by_owner.get(user.id, fallback_gym)
        membership_gym_by_user[user.id] = gym
        GymMembership.objects.get_or_create(
            user_id=user.id,
            gym_id=gym.id,
            defaults={
                'role': role_map.get(user.role, 'MEMBER'),
                'status': 'ACTIVE',
                'is_default': user.role == 'OWNER',
            },
        )

    def assign(model, user_field=None, fallback=True, related_gym_fields=None):
        for obj in model.objects.all():
            gym = None
            if user_field:
                gym = membership_gym_by_user.get(getattr(obj, f'{user_field}_id', None))
            if gym is None and related_gym_fields:
                for field in related_gym_fields:
                    related_id = getattr(obj, f'{field}_id', None)
                    if related_id:
                        related = model.objects.model._meta.get_field(field).related_model.objects.filter(pk=related_id).first()
                        gym = getattr(related, 'gym', None)
                        if gym:
                            break
            gym = gym or (fallback_gym if fallback else None)
            if gym is not None:
                model.objects.filter(pk=obj.pk).update(gym_id=gym.id)

    # User/people-owned records.
    assign(apps.get_model('members', 'MemberProfile'), 'user')
    assign(apps.get_model('staff', 'StaffProfile'), 'user')
    assign(apps.get_model('staff', 'LeaveRequest'), 'requester', related_gym_fields=['membership'])
    assign(apps.get_model('trainers', 'TrainerProfile'), 'user')
    assign(apps.get_model('trainers', 'TrainerMemberAssignment'), 'trainer')
    assign(apps.get_model('memberships', 'MembershipPlan'))
    assign(apps.get_model('memberships', 'Membership'), 'member')
    assign(apps.get_model('memberships', 'FreezeRequest'), related_gym_fields=['membership'])
    assign(apps.get_model('memberships', 'Offer'))
    assign(apps.get_model('memberships', 'PromoCode'), related_gym_fields=['offer'])
    assign(apps.get_model('memberships', 'PromoCodeUsage'), 'member')
    assign(apps.get_model('attendance', 'Attendance'), 'user')
    assign(apps.get_model('attendance', 'QRAttendanceToken'), 'member')
    assign(apps.get_model('attendance', 'BiometricRecord'), 'member')
    assign(apps.get_model('payments', 'Payment'), 'member')
    assign(apps.get_model('workouts', 'WorkoutTemplate'), 'trainer')
    assign(apps.get_model('workouts', 'WorkoutAssignment'), 'member', related_gym_fields=['template'])
    assign(apps.get_model('workouts', 'WorkoutCompletionLog'), related_gym_fields=['assignment'])
    assign(apps.get_model('diet', 'DietPlan'), 'member')
    assign(apps.get_model('diet', 'MealLog'), 'member')
    assign(apps.get_model('progress', 'ProgressEntry'), 'member')
    assign(apps.get_model('progress', 'PersonalRecord'), 'member')
    assign(apps.get_model('lockers', 'Locker'))
    assign(apps.get_model('lockers', 'LockerAssignment'), 'member', related_gym_fields=['locker'])
    assign(apps.get_model('equipment', 'Equipment'))
    assign(apps.get_model('equipment', 'MaintenanceRecord'), related_gym_fields=['equipment'])
    assign(apps.get_model('notifications', 'Notification'), 'recipient')
    assign(apps.get_model('notifications', 'MessageGroup'), 'created_by')
    assign(apps.get_model('notifications', 'GroupMessage'), 'sender', related_gym_fields=['group'])
    assign(apps.get_model('notifications', 'PinnedConversation'), 'user')
    assign(PlanSubscription, 'user')


def noop(apps, schema_editor):
    """Tenancy backfill is intentionally irreversible."""


class Migration(migrations.Migration):
    dependencies = [
        ('gyms', '0001_initial'),
        ('accounts', '0010_plansubscription_gym'),
        ('members', '0002_memberprofile_branch_memberprofile_gym_and_more'),
        ('memberships', '0008_freezerequest_branch_freezerequest_gym_and_more'),
        ('attendance', '0006_attendance_branch_attendance_gym_and_more'),
        ('payments', '0004_payment_branch_payment_gym'),
        ('staff', '0006_leaverequest_branch_leaverequest_gym_and_more'),
        ('trainers', '0003_trainermemberassignment_branch_and_more'),
        ('workouts', '0010_workoutcompletionlog_branch_workoutcompletionlog_gym'),
        ('diet', '0005_dietplan_branch_dietplan_gym_meallog_branch_and_more'),
        ('progress', '0003_personalrecord_branch_personalrecord_gym_and_more'),
        ('lockers', '0003_locker_branch_locker_gym_lockerassignment_branch_and_more'),
        ('equipment', '0004_equipment_branch_equipment_gym_and_more'),
        ('notifications', '0009_groupmessage_branch_groupmessage_gym_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_tenancy, noop),
    ]
