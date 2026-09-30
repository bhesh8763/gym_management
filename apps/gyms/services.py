"""Tenant provisioning and security-event services."""

from django.db import transaction
from django.utils import timezone

from .models import AuditLog, Branch, Gym, GymMembership


@transaction.atomic
def provision_owner_gym(*, user, name, owner_role=GymMembership.Role.OWNER):
    """Create the tenant and owner membership as one onboarding unit."""
    gym = Gym.objects.create(
        owner=user,
        name=name.strip() or f'{user.get_full_name()} Gym',
        status=Gym.Status.TRIAL,
    )
    membership = GymMembership.objects.create(
        user=user,
        gym=gym,
        role=owner_role,
        status=GymMembership.Status.ACTIVE,
        is_default=True,
    )
    Branch.objects.create(
        gym=gym,
        name='Main Branch',
        code='MAIN',
        is_primary=True,
    )
    return gym, membership


def primary_branch(gym):
    return gym.branches.filter(status=Branch.Status.ACTIVE, is_primary=True).first() or gym.branches.filter(status=Branch.Status.ACTIVE).first()


def mark_gym_onboarded(gym):
    gym.onboarding_complete = True
    gym.status = Gym.Status.ACTIVE
    gym.save(update_fields=['onboarding_complete', 'status', 'updated_at'])


def record_audit(*, gym, actor, action, request=None, target=None, metadata=None):
    """Write a compact audit event without making audit failures block requests."""
    target_type = ''
    target_id = ''
    if target is not None:
        target_type = target.__class__.__name__
        target_id = str(getattr(target, 'pk', ''))
    ip_address = None
    if request is not None:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        ip_address = (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None
    try:
        return AuditLog.objects.create(
            gym=gym,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
            ip_address=ip_address,
        )
    except Exception:
        # Audit logging must be observable but should not make a successful
        # business operation fail if the optional audit table is unavailable.
        return None
