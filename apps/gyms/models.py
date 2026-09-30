"""Multi-gym tenancy, branches, invitations, and audited owner sessions."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .managers import TenantManager


class Gym(models.Model):
    """A tenant/business that owns all operational gym data."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        TRIAL = 'TRIAL', 'Trial'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        CLOSED = 'CLOSED', 'Closed'

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gyms_owned',
    )
    public_id = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.TRIAL, db_index=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    timezone = models.CharField(max_length=64, default='Asia/Kathmandu')
    onboarding_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gyms'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.public_id})'

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = f'GY-{secrets.token_hex(3).upper()}'
        if not self.slug:
            base = slugify(self.name) or 'gym'
            self.slug = f'{base}-{self.public_id.lower()}'
        super().save(*args, **kwargs)


class GymMembership(models.Model):
    """A user's role and status inside one gym tenant."""

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        STAFF = 'STAFF', 'Receptionist'
        TRAINER = 'TRAINER', 'Trainer'
        MEMBER = 'MEMBER', 'Member'

    class Status(models.TextChoices):
        INVITED = 'INVITED', 'Invited'
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        INACTIVE = 'INACTIVE', 'Inactive'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gym_memberships',
    )
    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=10, choices=Role.choices, db_index=True)
    # Optional owner-defined role. When set, the effective permission set
    # comes from CustomRole.permissions (resolved per request) instead of
    # the built-in role's implicit set; ``role`` stores the derived base
    # level (STAFF/TRAINER/MEMBER) so legacy checks keep working.
    custom_role = models.ForeignKey(
        'CustomRole',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='memberships',
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    membership_number = models.CharField(max_length=30, blank=True)
    is_default = models.BooleanField(default=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_invitations_sent',
    )
    joined_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gym_memberships'
        ordering = ['gym__name', 'user__first_name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'gym'], name='unique_user_gym_membership'),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_default=True),
                name='one_default_gym_per_user',
            ),
            models.UniqueConstraint(
                fields=['gym', 'membership_number'],
                condition=~models.Q(membership_number=''),
                name='unique_gym_membership_number',
            ),
        ]
        indexes = [
            models.Index(fields=['gym', 'role', 'status'], name='idx_gym_membership_role'),
        ]

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.gym.public_id} ({self.role})'


class Branch(models.Model):
    """A physical location belonging to a gym."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        ARCHIVED = 'ARCHIVED', 'Archived'

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gym_branches'
        ordering = ['-is_primary', 'name']
        constraints = [
            models.UniqueConstraint(fields=['gym', 'code'], name='unique_gym_branch_code'),
            models.UniqueConstraint(
                fields=['gym'],
                condition=models.Q(is_primary=True),
                name='one_primary_branch_per_gym',
            ),
        ]

    def __str__(self):
        return f'{self.gym.public_id} / {self.name}'


class TenantScopedModel(models.Model):
    """Abstract tenant boundary shared by operational records.

    ``branch`` is nullable for records that belong to the whole gym. New API
    writes should populate ``gym`` and populate ``branch`` whenever the record
    is location-specific.

    Soft delete: concrete models get ``deleted_at``/``deleted_by`` plus three
    managers — ``objects`` (live rows only), ``all_objects`` (trash + live,
    for trash listing and restore) and ``base_objects`` (raw, no filtering,
    for FK traversal that must keep seeing deleted rows). ``delete()`` stamps
    ``deleted_at`` instead of removing the row; pass ``hard=True`` to really
    delete. ``restore()`` revives a trashed row.
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name='%(class)s_records',
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_records',
    )
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_deleted_records',
    )
    objects = TenantManager()
    all_objects = TenantManager(include_deleted=True)
    base_objects = models.Manager()

    def delete(self, using=None, keep_parents=False, hard=False, user=None):
        """Soft-delete by default; ``hard=True`` performs a real DELETE."""
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        from django.utils import timezone as _tz
        self.deleted_at = _tz.now()
        if user is not None:
            self.deleted_by = user
        self.save(update_fields=['deleted_at', 'deleted_by'])
        return self

    def restore(self, user=None):  # noqa: ARG002 - kept for API symmetry
        """Bring a soft-deleted row back to life."""
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['deleted_at', 'deleted_by'])
        return self

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def save(self, *args, **kwargs):
        from .managers import tenant_context
        try:
            context_gym = tenant_context.gym
        except AttributeError:
            context_gym = None
        if self.gym_id and self.branch_id:
            branch = self.branch
            if branch.gym_id != self.gym_id:
                from django.core.exceptions import ValidationError
                raise ValidationError({'branch': 'Branch must belong to the selected gym.'})
        if self.gym_id is None and self.branch_id:
            branch_gym_id = self.branch.gym_id
            if context_gym is not None and branch_gym_id != context_gym.id:
                from django.core.exceptions import ValidationError
                raise ValidationError({'branch': 'Branch is outside the active gym.'})
            self.gym_id = branch_gym_id
        if self.gym_id is None:
            if context_gym is not None:
                self.gym = context_gym
            else:
                user = None
                for field_name in ('user', 'member', 'recipient', 'trainer', 'created_by', 'requester', 'sender'):
                    if hasattr(self, f'{field_name}_id'):
                        user = getattr(self, field_name, None)
                        if user is not None:
                            break
                if user is not None:
                    memberships = list(user.gym_memberships.filter(
                        status=GymMembership.Status.ACTIVE,
                    ).values_list('gym_id', flat=True))
                    if len(set(memberships)) == 1:
                        self.gym_id = memberships[0]
        super().save(*args, **kwargs)

    class Meta:
        abstract = True


class BranchMembership(models.Model):
    """Explicit branch access for staff, trainers, and members."""

    gym_membership = models.ForeignKey(
        GymMembership,
        on_delete=models.CASCADE,
        related_name='branch_memberships',
    )
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='member_access')
    can_manage = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gym_branch_memberships'
        constraints = [
            models.UniqueConstraint(
                fields=['gym_membership', 'branch'],
                name='unique_branch_access_per_membership',
            ),
        ]

    def clean(self):
        if self.gym_membership_id and self.branch_id:
            if self.gym_membership.gym_id != self.branch.gym_id:
                from django.core.exceptions import ValidationError
                raise ValidationError('Branch must belong to the membership gym.')

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class Invitation(models.Model):
    """A one-time invitation to join a gym."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        REVOKED = 'REVOKED', 'Revoked'
        EXPIRED = 'EXPIRED', 'Expired'

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='invitations')
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invitations',
    )
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=GymMembership.Role.choices)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_invitations_created',
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gym_invitations_accepted',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'gym_invitations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['gym', 'email', 'status'], name='idx_gym_invitation_email'),
        ]

    def __str__(self):
        return f'{self.email} → {self.gym.public_id} ({self.role})'

    @classmethod
    def issue(cls, *, gym, email, role, invited_by=None, branch=None, expires_in_days=7):
        if branch is not None and branch.gym_id != gym.id:
            from django.core.exceptions import ValidationError
            raise ValidationError('Invitation branch must belong to the gym.')
        raw_token = secrets.token_urlsafe(48)
        invitation = cls.objects.create(
            gym=gym,
            branch=branch,
            email=email.lower(),
            role=role,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(days=expires_in_days),
        )
        return invitation, raw_token

    @property
    def is_valid(self):
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()


class ImpersonationSession(models.Model):
    """Short-lived, auditable owner access to another user's tenant view."""

    gym = models.ForeignKey(Gym, on_delete=models.CASCADE, related_name='impersonation_sessions')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='impersonation_sessions_started',
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='impersonation_sessions_received',
    )
    reason = models.CharField(max_length=255)
    jti = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'impersonation_sessions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.actor} viewing {self.subject} ({self.gym.public_id})'

    @property
    def is_active(self):
        return self.ended_at is None and self.expires_at > timezone.now()


class CustomRole(models.Model):
    """
    Owner-defined role with a granular permission set.

    GymMembership.custom_role points here instead of using the built-in
    OWNER/STAFF/TRAINER/MEMBER labels. The effective permission set is
    resolved per request (see apps.gyms.role_permissions) and enforced by
    RequiresPermission; the membership's base ``role`` is derived from the
    permissions (never OWNER) so legacy role checks keep working.
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name='custom_roles',
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='custom_roles_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'gym_custom_roles'
        verbose_name = 'Custom Role'
        verbose_name_plural = 'Custom Roles'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['gym', 'name'], name='unique_custom_role_name_per_gym'),
        ]

    def __str__(self):
        return f'{self.name} ({self.gym.public_id})'

    def clean_permissions(self):
        from .role_permissions import VALID_CODES
        invalid = [c for c in (self.permissions or []) if c not in VALID_CODES]
        if invalid:
            from django.core.exceptions import ValidationError
            raise ValidationError({'permissions': f'Unknown permission codes: {invalid}'})

    @property
    def base_role(self):
        """Built-in base level derived from the permission set."""
        from .role_permissions import level_for_permissions
        return level_for_permissions(self.permissions)


class AuditLog(models.Model):
    """Security and administrative audit events for a gym."""

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name='audit_logs',
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=80, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'gym_audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['gym', 'action', 'created_at'], name='idx_gym_audit_action'),
        ]

    def __str__(self):
        return f'{self.action} — {self.actor or "system"}'
