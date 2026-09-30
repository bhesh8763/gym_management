"""Helpers for resolving and enforcing the active gym/branch tenant."""

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from .managers import tenant_context
from .models import BranchMembership, GymMembership


def get_user_membership(user, gym_id=None):
    """Return the active membership used for this request, if any."""
    if not user or not user.is_authenticated:
        return None
    memberships = GymMembership.objects.filter(
        user=user,
        status=GymMembership.Status.ACTIVE,
        gym__status__in=['ACTIVE', 'TRIAL'],
    ).select_related('gym')
    if gym_id:
        memberships = memberships.filter(gym_id=gym_id)
    return memberships.order_by('-is_default', 'gym_id').first()


def resolve_request_tenant(request, user=None):
    """Attach gym/role/branch context to a DRF request.

    JWTs issued by the current authentication class carry ``gym_id``. The
    header fallback is useful during a gym switch and is still validated
    against a real active membership rather than trusted as an identifier.
    """
    if user is None:
        user = getattr(request, 'user', None)
    gym_id = request.headers.get('X-Gym-ID') if hasattr(request, 'headers') else None
    if not gym_id and hasattr(request, 'GET'):
        gym_id = request.GET.get('gym_id')
    if not gym_id:
        gym_id = getattr(request, 'jwt_claim_gym_id', None)

    invalid_gym_id = False
    if gym_id is not None:
        try:
            gym_id = int(gym_id)
        except (TypeError, ValueError):
            invalid_gym_id = True
            gym_id = None

    membership = None if invalid_gym_id else get_user_membership(user, gym_id)
    if membership is None:
        tenant_context.gym = None
        tenant_context.branch = None
        request.gym = None
        request.gym_id = None
        request.gym_membership = None
        request.gym_role = getattr(user, 'role', None)
        from .role_permissions import builtin_permissions
        request.effective_permissions = builtin_permissions(request.gym_role)
        request.branch = None
        request.branch_memberships = []
        return None

    request.gym = membership.gym
    request.gym_id = membership.gym_id
    tenant_context.gym = membership.gym
    request.gym_membership = membership
    request.gym_role = membership.role
    # Effective permissions: custom role set when assigned, otherwise the
    # built-in role's implicit set. Used by RequiresPermission and /auth/me/.
    from .role_permissions import resolve_permissions
    if membership.custom_role_id and membership.custom_role and membership.custom_role.is_active:
        request.effective_permissions = resolve_permissions(
            membership.role, membership.custom_role.permissions
        )
    else:
        request.effective_permissions = resolve_permissions(membership.role)
    request.branch_memberships = list(
        BranchMembership.objects.filter(
            gym_membership=membership,
            branch__status='ACTIVE',
        ).select_related('branch')
    )
    branch_id = request.headers.get('X-Branch-ID') if hasattr(request, 'headers') else None
    if not branch_id and hasattr(request, 'GET'):
        branch_id = request.GET.get('branch_id')
    invalid_branch_id = False
    if branch_id is not None:
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            invalid_branch_id = True
            branch_id = None
    request.branch = None
    tenant_context.branch = None
    if branch_id:
        request.branch = next(
            (access.branch for access in request.branch_memberships if access.branch_id == branch_id),
            None,
        )
        if request.branch is None and membership.role == GymMembership.Role.OWNER:
            from .models import Branch
            request.branch = Branch.objects.filter(
                pk=branch_id,
                gym=membership.gym,
                status=Branch.Status.ACTIVE,
            ).first()
        if request.branch is None:
            raise PermissionDenied('You do not have access to the requested branch.')
        tenant_context.branch = request.branch
    elif invalid_branch_id:
        raise PermissionDenied('Invalid branch ID.')
    elif membership.role == GymMembership.Role.OWNER:
        request.branch = None
        tenant_context.branch = None
    else:
        if len(request.branch_memberships) == 1:
            request.branch = request.branch_memberships[0].branch
        elif len(request.branch_memberships) == 0:
            raise PermissionDenied('Your account has no branch access.')
        else:
            raise PermissionDenied('X-Branch-ID is required for this account.')
        tenant_context.branch = request.branch
    return membership


def user_has_branch_access(user, gym, branch):
    """Return whether a user may be targeted in the selected branch."""
    if gym is None or branch is None:
        return True
    membership = GymMembership.objects.filter(
        gym=gym,
        user=user,
        status=GymMembership.Status.ACTIVE,
    ).first()
    if membership is None:
        return False
    if membership.role == GymMembership.Role.OWNER:
        return True
    return membership.branch_memberships.filter(branch=branch).exists()


def gym_users(*, gym, role=None, active=True):
    """Return users with an active membership in the selected gym."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if gym is None:
        queryset = User.objects.all()
        if active:
            queryset = queryset.filter(is_active=True)
        if role is not None:
            if isinstance(role, (list, tuple, set)):
                queryset = queryset.filter(role__in=role)
            else:
                queryset = queryset.filter(role=role)
        return queryset.distinct()
    memberships = {'gym': gym}
    if role is not None:
        if isinstance(role, (list, tuple, set)):
            memberships['role__in'] = role
        else:
            memberships['role'] = role
    if active:
        memberships['status'] = GymMembership.Status.ACTIVE
    lookup = {f'gym_memberships__{key}': value for key, value in memberships.items()}
    return User.objects.filter(**lookup).distinct()


def tenant_queryset(queryset, request, field='gym'):
    """Scope a queryset to the request gym, with an explicit legacy fallback.

    Existing installations are backfilled by migration. While the compatibility
    switch is enabled, records created before tenancy rollout remain readable;
    new API writes still use :func:`assign_tenant`.
    """
    gym = getattr(request, 'gym', None)
    if gym is not None:
        return queryset.filter(**{field: gym})
    if getattr(settings, 'TENANCY_REQUIRE_MEMBERSHIP', False):
        raise PermissionDenied('An active gym membership is required.')
    return queryset


def branch_queryset(queryset, request, field='branch'):
    """Apply a branch while keeping explicitly gym-wide records visible."""
    from django.db.models import Q
    branch = getattr(request, 'branch', None)
    if branch is not None:
        return queryset.filter(Q(**{field: branch}) | Q(**{f'{field}__isnull': True}))
    return queryset


def assign_tenant(instance, request, branch=True):
    """Set tenant fields on a new model instance from trusted request context."""
    if hasattr(instance, 'gym_id'):
        instance.gym = getattr(request, 'gym', None)
    if branch and hasattr(instance, 'branch_id'):
        instance.branch = getattr(request, 'branch', None)
    return instance


def user_has_role(request, *roles):
    return getattr(request, 'gym_role', None) in roles
