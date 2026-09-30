"""
Role-Based Access Control (RBAC) for the Gym Management System.

Usage in views:
    permission_classes = [IsOwner]
    permission_classes = [IsOwnerOrStaff]
    permission_classes = [IsTrainer]

Decorator usage (function-based views):
    @role_required('OWNER', 'STAFF')
    def my_view(request): ...
"""
from functools import wraps

from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.models import User


def _role_for_request(request):
    return getattr(request, 'gym_role', None) or getattr(request.user, 'role', None)


def _tenant_allowed(request):
    # Legacy data is readable while the rollout switch is off. Production sets
    # TENANCY_REQUIRE_MEMBERSHIP=True so an unscoped token cannot use the API.
    if getattr(settings, 'TENANCY_REQUIRE_MEMBERSHIP', False):
        return bool(getattr(request, 'gym_membership', None))
    return True


def _subscription_allowed(request, gym=None, role=None):
    """Require a paid gym plan for owner-only management APIs when enabled."""
    if not getattr(settings, 'REQUIRE_OWNER_SUBSCRIPTION', False):
        return True
    if (role or _role_for_request(request)) != User.Role.OWNER:
        return True
    from apps.accounts.models import PlanSubscription
    gym = gym or getattr(request, 'gym', None)
    if gym is None:
        return False
    return PlanSubscription.objects.filter(
        user=request.user,
        gym=gym,
        status='paid',
    ).exists()


def subscription_allowed(request, gym=None, role=None):
    """Public wrapper for custom tenant views that perform their own RBAC."""
    return _subscription_allowed(request, gym=gym, role=role)


# ─── Base Role Permission ──────────────────────────────────────────────────────

class HasRole(BasePermission):
    """
    Generic base permission class. Subclasses define `allowed_roles`.
    """
    allowed_roles = []

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and _tenant_allowed(request)
            and _subscription_allowed(request)
            and _role_for_request(request) in self.allowed_roles
        )


# ─── Single-Role Permissions ──────────────────────────────────────────────────

class IsOwner(HasRole):
    """Only gym owners."""
    allowed_roles = [User.Role.OWNER]
    message = 'Access restricted to gym owners.'


class IsStaff(HasRole):
    """Only gym staff."""
    allowed_roles = [User.Role.STAFF]
    message = 'Access restricted to gym staff.'


class IsTrainer(HasRole):
    """Only trainers."""
    allowed_roles = [User.Role.TRAINER]
    message = 'Access restricted to trainers.'


class IsMember(HasRole):
    """Only members."""
    allowed_roles = [User.Role.MEMBER]
    message = 'Access restricted to members.'


class IsAdmin(HasRole):
    """Only admins (developers)."""
    allowed_roles = [User.Role.ADMIN]
    message = 'Access restricted to admins.'


# ─── Combined-Role Permissions ────────────────────────────────────────────────

class IsOwnerOrStaff(HasRole):
    """Owners and staff (admin-side operations)."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF]
    message = 'Access restricted to owners and staff.'


class IsOwnerOrStaffOrTrainer(HasRole):
    """Owners, staff, and trainers."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER]
    message = 'Access restricted to owners, staff, and trainers.'

class IsOwnerOrStaffOrTrainerOrMember(HasRole):
    """Owners, staff, trainers, and members — for endpoints where each role sees only their own data."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER, User.Role.MEMBER, User.Role.ADMIN]
    message = 'Authentication required.'
class IsTrainerOrMember(HasRole):
    """Trainers and members."""
    allowed_roles = [User.Role.TRAINER, User.Role.MEMBER]
    message = 'Access restricted to trainers and members.'


class IsAnyStaffRole(HasRole):
    """All non-member roles (owner, staff, trainer)."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER, User.Role.ADMIN]
    message = 'Access restricted to staff members.'


class IsOwnerOrStaffOrMemberReadOnly(BasePermission):
    """
    Owner/Staff get full CRUD. Members get read-only access (GET, HEAD, OPTIONS).
    """
    message = 'You do not have permission to perform this action.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated or not _tenant_allowed(request) or not _subscription_allowed(request):
            return False
        role = _role_for_request(request)
        if role in [User.Role.OWNER, User.Role.STAFF, User.Role.ADMIN]:
            return True
        if role == User.Role.MEMBER and request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return False


# ─── Object-Level: Owner of Record ────────────────────────────────────────────

class IsOwnerOfObject(BasePermission):
    """
    Object-level permission: only the user who owns the object can access it.
    The object must have a `user` field pointing to a User instance.
    """
    message = 'You do not have permission to access this record.'

    def has_object_permission(self, request, view, obj):
        if not _tenant_allowed(request) or not _subscription_allowed(request):
            return False
        if hasattr(obj, 'gym_id') and getattr(request, 'gym', None) is not None:
            if obj.gym_id != request.gym.id:
                return False
        return obj.user == request.user


class IsOwnerOrStaffOrOwnerOfObject(BasePermission):
    """
    Owners/Staff can access any object.
    Other roles can only access their own objects (obj.user == request.user).
    """
    message = 'You do not have permission to access this record.'

    def has_object_permission(self, request, view, obj):
        if not _tenant_allowed(request) or not _subscription_allowed(request):
            return False
        if hasattr(obj, 'gym_id') and getattr(request, 'gym', None) is not None:
            if obj.gym_id != request.gym.id:
                return False
        if _role_for_request(request) in [User.Role.OWNER, User.Role.STAFF, User.Role.ADMIN]:
            return True
        return hasattr(obj, 'user') and obj.user == request.user


# ─── Decorator for Function-Based Views ───────────────────────────────────────

class RequiresPermission(BasePermission):
    """
    Granular permission check against the request's effective permission set.

    Usage:
        permission_classes = [IsAuthenticated, RequiresPermission]
        required_permissions = ['payments.manage']

    The request's effective_permissions are attached by
    resolve_request_tenant (built-in roles get their implicit sets; custom
    roles get exactly what the owner granted).
    """
    message = 'You do not have permission to perform this action.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not _tenant_allowed(request):
            return False
        required = getattr(view, 'required_permissions', None)
        if not required:
            # Misconfigured view — deny rather than silently allow.
            return False
        perms = getattr(request, 'effective_permissions', None)
        if perms is None:
            # Tenancy never ran (e.g. tests hitting the view directly).
            from apps.gyms.role_permissions import builtin_permissions
            perms = builtin_permissions(_role_for_request(request))
        return all(code in perms for code in required)


def role_required(*roles):
    """
    Decorator for DRF function-based views.

    Example:
        @api_view(['GET'])
        @role_required(User.Role.OWNER, User.Role.STAFF)
        def dashboard_summary(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user or not request.user.is_authenticated:
                raise PermissionDenied('Authentication required.')
            if not _tenant_allowed(request) or not _subscription_allowed(request):
                raise PermissionDenied('An active gym membership and subscription are required.')
            if _role_for_request(request) not in roles:
                raise PermissionDenied(
                    f'This action requires one of the following roles: {", ".join(roles)}.'
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
