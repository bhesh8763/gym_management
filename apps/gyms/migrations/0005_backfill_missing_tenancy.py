from django.db import migrations


TENANT_MODELS = [
    ('members', 'MemberProfile'),
    ('staff', 'StaffProfile', 'user'),
    ('staff', 'LeaveRequest', 'requester', ('membership',)),
    ('trainers', 'TrainerProfile', 'user'),
    ('trainers', 'TrainerMemberAssignment', 'trainer'),
    ('memberships', 'MembershipPlan'),
    ('memberships', 'Membership', 'member', ('plan',)),
    ('memberships', 'FreezeRequest', None, ('membership',)),
    ('memberships', 'Offer'),
    ('memberships', 'PromoCode', None, ('offer',)),
    ('memberships', 'PromoCodeUsage', 'member', ('promo_code', 'membership')),
    ('attendance', 'Attendance', 'user'),
    ('attendance', 'QRAttendanceToken', 'member'),
    ('attendance', 'BiometricRecord', 'member'),
    ('payments', 'Payment', 'member', ('membership',)),
    ('workouts', 'WorkoutTemplate', 'trainer'),
    ('workouts', 'WorkoutAssignment', 'member', ('template',)),
    ('workouts', 'WorkoutCompletionLog', None, ('assignment',)),
    ('diet', 'DietPlan', 'member'),
    ('diet', 'MealLog', 'member'),
    ('progress', 'ProgressEntry', 'member'),
    ('progress', 'PersonalRecord', 'member', ('assignment', 'log')),
    ('lockers', 'Locker'),
    ('lockers', 'LockerAssignment', 'member', ('locker',)),
    ('equipment', 'Equipment'),
    ('equipment', 'MaintenanceRecord', None, ('equipment',)),
    ('notifications', 'Notification', 'recipient', ('sender',)),
    ('notifications', 'MessageGroup', 'created_by'),
    ('notifications', 'GroupMessage', 'sender', ('group',)),
    ('notifications', 'PinnedConversation', 'user'),
]


def _related_gym(model, instance, field_names):
    meta = model._meta
    for field_name in field_names:
        try:
            field = meta.get_field(field_name)
        except Exception:
            continue
        related_id = getattr(instance, f'{field_name}_id', None)
        if not related_id:
            continue
        related_model = field.remote_field.model
        related = related_model.objects.filter(pk=related_id).first()
        gym = getattr(related, 'gym', None)
        if gym is not None:
            return gym
    return None


def backfill_missing_tenancy(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    Gym = apps.get_model('gyms', 'Gym')
    GymMembership = apps.get_model('gyms', 'GymMembership')
    PlanSubscription = apps.get_model('accounts', 'PlanSubscription')
    alias = schema_editor.connection.alias

    gyms = list(Gym.objects.using(alias).all())
    if not gyms:
        return
    fallback_gym = gyms[0]
    primary_branches = {
        gym.id: (gym.branches.using(alias).filter(is_primary=True).first() or gym.branches.using(alias).first())
        for gym in gyms
    }
    membership_gym_by_user = {}
    for membership in GymMembership.objects.using(alias).filter(status='ACTIVE').select_related('gym'):
        membership_gym_by_user.setdefault(membership.user_id, membership.gym)

    for spec in TENANT_MODELS:
        app_label, model_name, *rest = spec
        user_field = rest[0] if rest and rest[0] else None
        related_fields = rest[1] if len(rest) > 1 else ()
        model = apps.get_model(app_label, model_name)
        for instance in model.objects.using(alias).filter(gym_id__isnull=True):
            gym = None
            if user_field:
                user_id = getattr(instance, f'{user_field}_id', None)
                gym = membership_gym_by_user.get(user_id)
            if gym is None:
                gym = _related_gym(model, instance, related_fields)
            gym = gym or fallback_gym
            updates = {'gym_id': gym.id}
            if 'branch_id' in {field.name for field in model._meta.fields}:
                branch = primary_branches.get(gym.id)
                if branch is not None and instance.branch_id is None:
                    updates['branch_id'] = branch.id
            model.objects.using(alias).filter(pk=instance.pk).update(**updates)

    # PlanSubscription is not a TenantScopedModel but is still gym-scoped.
    for subscription in PlanSubscription.objects.using(alias).filter(gym_id__isnull=True):
        gym = membership_gym_by_user.get(subscription.user_id) or fallback_gym
        PlanSubscription.objects.using(alias).filter(pk=subscription.pk).update(gym_id=gym.id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('gyms', '0004_gymmembership_one_default_gym_per_user'),
    ]

    operations = [
        migrations.RunPython(backfill_missing_tenancy, noop),
    ]
