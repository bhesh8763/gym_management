"""
Custom User model with role-based access control.
Roles: Owner, Staff, Trainer, Member
"""
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
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
