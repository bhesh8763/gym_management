"""
Serializers for authentication and user management.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer

from .models import PlanSubscription

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default JWT pair serializer to embed user info into the token
    and return it in the response payload.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Custom claims embedded in JWT payload
        token['email'] = user.email
        token['full_name'] = user.get_full_name()
        token['role'] = user.role
        token['token_version'] = user.token_version
        from apps.gyms.tenancy import get_user_membership
        membership = get_user_membership(user)
        if membership:
            token['gym_id'] = membership.gym_id
            token['gym_role'] = membership.role
            token['gym_public_id'] = membership.gym.public_id
            token['role'] = membership.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Append user info to the login response body.
        # Pass request through context so profile_picture gets a proper
        # absolute URL (e.g. http://127.0.0.1:8000/media/...) rather than
        # falling back to the SITE_URL setting.
        request = self.context.get('request')
        data['user'] = UserDetailSerializer(self.user, context={'request': request}).data
        return data


class TenantTokenRefreshSerializer(TokenRefreshSerializer):
    """Validate tenant/impersonation state before rotating a refresh token."""

    def validate(self, attrs):
        from django.conf import settings
        from apps.gyms.models import ImpersonationSession
        from apps.gyms.tenancy import get_user_membership

        refresh = self.token_class(attrs['refresh'])
        user = User.objects.filter(pk=refresh.get('user_id'), is_active=True).first()
        if user is None:
            raise InvalidToken('User account is inactive or missing.')

        claimed_version = refresh.get('token_version')
        if claimed_version is not None:
            try:
                version_matches = int(claimed_version) == int(user.token_version or 0)
            except (TypeError, ValueError):
                version_matches = False
            if not version_matches:
                raise InvalidToken('User session has been invalidated.')

        impersonation_id = refresh.get('impersonation_id')
        if impersonation_id is not None:
            session = ImpersonationSession.objects.select_related('actor', 'subject').filter(
                pk=impersonation_id,
            ).first()
            if (
                session is None
                or not session.is_active
                or session.subject_id != user.id
                or session.actor_id != refresh.get('actor_id')
                or str(session.gym_id) != str(refresh.get('gym_id'))
            ):
                raise InvalidToken('Impersonation session is invalid or expired.')

        gym_id = refresh.get('gym_id')
        if gym_id is not None:
            try:
                gym_id = int(gym_id)
            except (TypeError, ValueError):
                raise InvalidToken('The gym claim is malformed.')
            membership = get_user_membership(user, gym_id)
            if membership is None:
                raise InvalidToken('The gym membership is no longer active.')
            claimed_role = refresh.get('gym_role')
            if claimed_role and claimed_role != membership.role:
                raise InvalidToken('The gym role has changed; sign in again.')
        elif getattr(settings, 'TENANCY_REQUIRE_MEMBERSHIP', False):
            raise InvalidToken('An active gym membership is required.')

        return super().validate(attrs)


class RegisterSerializer(serializers.ModelSerializer):
    """
    Handles new user (public, self-service) registration.
    Password is write-only and validated against Django password validators.

    Always creates an OWNER — public signup is the gym-owner onboarding flow:
    the account registers, picks a plan on payment.html, then manages the gym.
    Members/Staff/Trainers are added later by the Owner through the dedicated
    "add" endpoints instead. The endpoint is open (AllowAny), so it still must
    never accept a caller-supplied role — the role is fixed server-side no
    matter what the payload claims.
    """
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password2 = serializers.CharField(write_only=True, required=True, label='Confirm password')
    gym_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=150)

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name', 'phone',
            'password', 'password2', 'gym_name',
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        gym_name = validated_data.pop('gym_name', '')
        password = validated_data.pop('password')
        user = User(role=User.Role.OWNER, is_staff=True, **validated_data)
        user.set_password(password)
        user.save()

        from apps.gyms.services import provision_owner_gym
        provision_owner_gym(
            user=user,
            name=gym_name or f'{user.get_full_name()} Gym',
        )
        return user


class SubscribeSerializer(serializers.Serializer):
    """
    Validates the simulated checkout payload from payment.html. The price is
    intentionally absent from the fields — it is derived server-side from
    PLAN_PRICES so a tampered client can't pick its own amount.
    """
    plan = serializers.ChoiceField(choices=PlanSubscription.PLAN_CHOICES)
    method = serializers.ChoiceField(choices=PlanSubscription.METHOD_CHOICES)


class UserDetailSerializer(serializers.ModelSerializer):
    """
    Read-only serializer used for user profile responses and JWT payload.
    """
    full_name = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    gym_id = serializers.SerializerMethodField()
    gym_public_id = serializers.SerializerMethodField()
    gym_role = serializers.SerializerMethodField()
    gym_custom_role = serializers.SerializerMethodField()
    gym_permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'display_id', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'role', 'profile_picture',
            'gym_id', 'gym_public_id', 'gym_role', 'gym_custom_role', 'gym_permissions',
            'is_active', 'date_joined', 'last_login',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        url = obj.profile_picture.url
        if request:
            return request.build_absolute_uri(url)
        # No request in context (e.g. called from login serializer) — build
        # the absolute URL from MEDIA_URL and the configured host directly.
        from django.conf import settings
        base = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
        return f"{base}{url}"

    def _membership(self, obj):
        from apps.gyms.tenancy import get_user_membership
        request = self.context.get('request')
        gym_id = getattr(request, 'gym_id', None) if request else None
        return get_user_membership(obj, gym_id)

    def get_gym_id(self, obj):
        membership = self._membership(obj)
        return membership.gym_id if membership else None

    def get_gym_public_id(self, obj):
        membership = self._membership(obj)
        return membership.gym.public_id if membership else None

    def get_gym_role(self, obj):
        membership = self._membership(obj)
        return membership.role if membership else obj.role

    def get_gym_custom_role(self, obj):
        """Name of the owner-defined role on the active membership, if any."""
        membership = self._membership(obj)
        if membership and membership.custom_role_id and membership.custom_role:
            return membership.custom_role.name
        return None

    def get_gym_permissions(self, obj):
        """Effective permission codes for the active membership.

        Drives the frontend's sidebar/menu visibility for custom roles.
        """
        from apps.gyms.role_permissions import resolve_permissions
        membership = self._membership(obj)
        if membership is None:
            from apps.gyms.role_permissions import builtin_permissions
            return sorted(builtin_permissions(obj.role))
        if membership.custom_role_id and membership.custom_role and membership.custom_role.is_active:
            return sorted(resolve_permissions(membership.role, membership.custom_role.permissions))
        return sorted(resolve_permissions(membership.role))


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Allows users to update their own profile (name, email, phone, picture).
    Role changes are not allowed here.
    """

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'profile_picture']


class ChangePasswordSerializer(serializers.Serializer):
    """Handles authenticated password change."""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True, write_only=True, validators=[validate_password]
    )
    new_password2 = serializers.CharField(required=True, write_only=True, label='Confirm new password')

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password': 'Passwords do not match.'})
        return attrs

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Old password is incorrect.')
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user
