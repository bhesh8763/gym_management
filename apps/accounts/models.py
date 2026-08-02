"""
Custom User model with role-based access control.
Roles: Owner, Staff, Trainer, Member
"""
import secrets
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models, transaction
from django.utils import timezone



class UserManager(BaseUserManager):
    """Custom manager for User model."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email address is required.')
        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.OWNER)

        if not extra_fields.get('is_staff'):
            raise ValueError('Superuser must have is_staff=True.')
        if not extra_fields.get('is_superuser'):
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class RoleSequence(models.Model):
    """
    Tracks the last-used sequence number per role, used to generate
    human-readable display IDs like MEM-0001, STF-0001, TRN-0001, OWN-0001.
    """
    role = models.CharField(max_length=10, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'role_sequences'

    def __str__(self):
        return f'{self.role}: {self.last_value}'


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central user model shared by all roles.
    Role determines access level and linked profile.
    """

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        STAFF = 'STAFF', 'Staff'
        TRAINER = 'TRAINER', 'Trainer'
        MEMBER = 'MEMBER', 'Member'

    ROLE_PREFIXES = {
        Role.OWNER: 'OWN',
        Role.STAFF: 'STF',
        Role.TRAINER: 'TRN',
        Role.MEMBER: 'MEM',
    }

    # Core identity
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(
        upload_to='profile_pictures/', null=True, blank=True
    )

    # Role
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
        db_index=True,
    )

    # Human-readable role-based ID, e.g. MEM-0001
    display_id = models.CharField(
        max_length=20, unique=True, editable=False, null=True, blank=True
    )

    # Django required fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        return f'{self.get_full_name()} ({self.role})'

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def get_short_name(self):
        return self.first_name

    def save(self, *args, **kwargs):
        if not self.display_id:
            self.display_id = self._generate_display_id()
        super().save(*args, **kwargs)

    def _generate_display_id(self):
        prefix = self.ROLE_PREFIXES.get(self.role, 'USR')
        with transaction.atomic():
            seq, _ = RoleSequence.objects.select_for_update().get_or_create(
                role=self.role
            )
            seq.last_value += 1
            seq.save(update_fields=['last_value'])
            return f'{prefix}-{seq.last_value:04d}'

    # ─── Role helpers ─────────────────────────────────────────────────────────
    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_gym_staff(self):
        return self.role == self.Role.STAFF

    @property
    def is_trainer(self):
        return self.role == self.Role.TRAINER

    @property
    def is_member(self):
        return self.role == self.Role.MEMBER


class PasswordResetToken(models.Model):
    """
    One-time token for email-based password reset.
    Each new request invalidates any previous tokens for the same user.
    """
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='password_reset_tokens',
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = 'password_reset_tokens'
        verbose_name = 'Password Reset Token'
        ordering = ['-created_at']

    def __str__(self):
        return f'Reset token for {self.user.email}'

    @classmethod
    def create_for_user(cls, user):
        """Invalidate old tokens, create a new one valid for 1 hour."""
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        token = secrets.token_urlsafe(48)
        return cls.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )

    @property
    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()
