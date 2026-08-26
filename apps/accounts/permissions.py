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

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.models import User


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
            and request.user.role in self.allowed_roles
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


# ─── Combined-Role Permissions ────────────────────────────────────────────────

class IsOwnerOrStaff(HasRole):
    """Owners and staff (admin-side operations)."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF]
    message = 'Access restricted to owners and staff.'


class IsOwnerOrStaffOrTrainer(HasRole):
    """Owners, staff, and trainers."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER]
    message = 'Access restricted to owners, staff, and trainers.'


class IsTrainerOrMember(HasRole):
    """Trainers and members."""
    allowed_roles = [User.Role.TRAINER, User.Role.MEMBER]
    message = 'Access restricted to trainers and members.'


class IsAnyStaffRole(HasRole):
    """All non-member roles (owner, staff, trainer)."""
    allowed_roles = [User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER]
    message = 'Access restricted to staff members.'


class IsOwnerOrStaffOrMemberReadOnly(BasePermission):
    """
    Owner/Staff get full CRUD. Members get read-only access (GET, HEAD, OPTIONS).
    """
    message = 'You do not have permission to perform this action.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.role in [User.Role.OWNER, User.Role.STAFF]:
            return True
        if request.user.role == User.Role.MEMBER and request.method in ('GET', 'HEAD', 'OPTIONS'):
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
        return obj.user == request.user


class IsOwnerOrStaffOrOwnerOfObject(BasePermission):
    """
    Owners/Staff can access any object.
    Other roles can only access their own objects (obj.user == request.user).
    """
    message = 'You do not have permission to access this record.'

    def has_object_permission(self, request, view, obj):
        if request.user.role in [User.Role.OWNER, User.Role.STAFF]:
            return True
        return hasattr(obj, 'user') and obj.user == request.user


# ─── Decorator for Function-Based Views ───────────────────────────────────────

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
            if request.user.role not in roles:
                raise PermissionDenied(
                    f'This action requires one of the following roles: {", ".join(roles)}.'
                )
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
