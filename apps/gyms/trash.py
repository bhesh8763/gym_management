"""
Soft-delete trash registry.

Maps a short slug to the model + serializer used by the Trash API
(list / restore / purge). A model participates simply by being registered
here — no per-app view changes required.
"""
from django.apps import apps as _apps

# slug -> {"model": <Model class or "app.Model" label>, "serializer": <path>}
TRASH_REGISTRY = {
    'members': {
        'model': 'members.MemberProfile',
        'serializer': 'apps.members.serializers.MemberProfileSerializer',
    },
    'memberships': {
        'model': 'memberships.Membership',
        'serializer': 'apps.memberships.serializers.MembershipDetailSerializer',
    },
    'plans': {
        'model': 'memberships.MembershipPlan',
        'serializer': 'apps.memberships.serializers.MembershipPlanSerializer',
    },
    'offers': {
        'model': 'memberships.Offer',
        'serializer': 'apps.memberships.serializers.OfferSerializer',
    },
    'promo-codes': {
        'model': 'memberships.PromoCode',
        'serializer': 'apps.memberships.serializers.PromoCodeSerializer',
    },
    'payments': {
        'model': 'payments.Payment',
        'serializer': 'apps.payments.serializers.PaymentSerializer',
    },
    'staff': {
        'model': 'staff.StaffProfile',
        'serializer': 'apps.staff.serializers.StaffProfileSerializer',
    },
    'trainers': {
        'model': 'trainers.TrainerProfile',
        'serializer': 'apps.trainers.serializers.TrainerProfileSerializer',
    },
    'trainer-assignments': {
        'model': 'trainers.TrainerMemberAssignment',
        'serializer': 'apps.trainers.serializers.TrainerMemberAssignmentSerializer',
    },
    'attendance': {
        'model': 'attendance.Attendance',
        'serializer': 'apps.attendance.serializers.AttendanceSerializer',
    },
    'diet-plans': {
        'model': 'diet.DietPlan',
        'serializer': 'apps.diet.serializers.DietPlanSerializer',
    },
    'workout-plans': {
        'model': 'workouts.WorkoutTemplate',
        'serializer': 'apps.workouts.serializers.WorkoutTemplateSerializer',
    },
    'equipment': {
        'model': 'equipment.Equipment',
        'serializer': 'apps.equipment.serializers.EquipmentSerializer',
    },
    'lockers': {
        'model': 'lockers.Locker',
        'serializer': 'apps.lockers.serializers.LockerSerializer',
    },
    'locker-assignments': {
        'model': 'lockers.LockerAssignment',
        'serializer': 'apps.lockers.serializers.LockerAssignmentSerializer',
    },
}

_CACHE = {}


def _resolve(key):
    """Lazily resolve model/serializer classes to avoid import cycles."""
    if key in _CACHE:
        return _CACHE[key]
    entry = TRASH_REGISTRY[key]
    model = _apps.get_model(entry['model'])
    if 'serializer' in entry:
        mod_path, cls_name = entry['serializer'].rsplit('.', 1)
        import importlib
        serializer_cls = getattr(importlib.import_module(mod_path), cls_name)
    else:
        serializer_cls = None
    _CACHE[key] = (model, serializer_cls)
    return _CACHE[key]


def get_model(slug):
    """Return the model class for a trash slug, or None."""
    if slug not in TRASH_REGISTRY:
        return None
    return _resolve(slug)[0]


def get_serializer_class(slug):
    """Return the serializer class for a trash slug, or None."""
    if slug not in TRASH_REGISTRY:
        return None
    return _resolve(slug)[1]


def deleted_queryset(model, gym):
    """Return the soft-deleted rows of `model` scoped to `gym`."""
    return model.all_objects.filter(gym=gym, deleted_at__isnull=False)
