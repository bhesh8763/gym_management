from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Branch, BranchMembership, CustomRole, Gym, GymMembership, Invitation

# Sentinel distinguishing "field not provided" from an explicit null.
_UNSET = object()


User = get_user_model()


class GymSerializer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    branch_count = serializers.SerializerMethodField()

    class Meta:
        model = Gym
        fields = [
            'id', 'public_id', 'name', 'slug', 'status', 'owner', 'owner_name',
            'address', 'phone', 'timezone', 'onboarding_complete',
            'member_count', 'branch_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'public_id', 'slug', 'owner', 'onboarding_complete', 'created_at', 'updated_at']

    def get_owner_name(self, obj):
        return obj.owner.get_full_name() if obj.owner_id else ''

    def get_member_count(self, obj):
        return obj.memberships.filter(status=GymMembership.Status.ACTIVE).count()

    def get_branch_count(self, obj):
        return obj.branches.filter(status=Branch.Status.ACTIVE).count()


class GymMembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    display_id = serializers.CharField(source='user.display_id', read_only=True)
    branch_names = serializers.SerializerMethodField()

    class Meta:
        model = GymMembership
        fields = [
            'id', 'gym', 'user_id', 'full_name', 'email', 'display_id',
            'role', 'status', 'membership_number', 'is_default',
            'branch_names', 'joined_at', 'created_at',
        ]
        read_only_fields = fields

    def get_branch_names(self, obj):
        return [
            access.branch.name
            for access in obj.branch_memberships.select_related('branch').filter(
                branch__status=Branch.Status.ACTIVE,
            )
        ]


class GymMembershipUpdateSerializer(serializers.ModelSerializer):
    branch_ids = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )
    # Owner-defined custom role. Send null to clear it (falls back to the
    # builtin role's permission set).
    custom_role = serializers.PrimaryKeyRelatedField(
        queryset=CustomRole.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = GymMembership
        fields = ['role', 'status', 'membership_number', 'branch_ids', 'custom_role']
        read_only_fields = []

    def validate_branch_ids(self, value):
        gym = self.context['gym']
        if any(
            branch.gym_id != gym.id or branch.status != Branch.Status.ACTIVE
            for branch in value
        ):
            raise serializers.ValidationError('All branches must be active in this gym.')
        return value

    def validate_custom_role(self, value):
        if value is None:
            return value
        gym = self.context['gym']
        if value.gym_id != gym.id:
            raise serializers.ValidationError('Custom role must belong to this gym.')
        if not value.is_active:
            raise serializers.ValidationError('This custom role is inactive.')
        return value

    def validate(self, attrs):
        # Assigning a custom role derives the membership's base role from the
        # role's permissions (never OWNER) — that would silently demote an
        # owner. Custom roles are for staff/trainer/member memberships only.
        target = self.instance
        if target is not None and target.role == GymMembership.Role.OWNER:
            if 'custom_role' in attrs and attrs['custom_role'] is not None:
                raise serializers.ValidationError(
                    {'custom_role': 'Custom roles cannot be assigned to an owner membership.'}
                )
        return attrs

    def update(self, instance, validated_data):
        branch_ids = validated_data.pop('branch_ids', None)
        # Pop with a sentinel so "not provided" and "explicit null" (unassign)
        # stay distinguishable.
        custom_role = validated_data.pop('custom_role', _UNSET)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if custom_role is not _UNSET:
            instance.custom_role = custom_role
            if custom_role is not None:
                # Keep the builtin role in sync with the derived base level so
                # legacy role checks (page guards, IsOwnerOrStaff, …) keep
                # working. Never OWNER — see level_for_permissions.
                instance.role = custom_role.base_role
        instance.save()
        if branch_ids is not None:
            instance.branch_memberships.all().delete()
            instance.branch_memberships.bulk_create([
                BranchMembership(gym_membership=instance, branch=branch)
                for branch in branch_ids
            ])
        return instance


class GymMembershipCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, write_only=True)
    role = serializers.ChoiceField(choices=GymMembership.Role.choices)
    membership_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    branch_id = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )

    def validate(self, attrs):
        gym = self.context['gym']
        user = User.objects.filter(email__iexact=attrs['email']).first()
        if user and GymMembership.objects.filter(user=user, gym=gym).exists():
            raise serializers.ValidationError('This user is already a member of this gym.')
        if not user and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'A password is required for a new user.'})
        if attrs.get('password'):
            validate_password(attrs['password'])
        branch = attrs.get('branch_id')
        if branch and (
            branch.gym_id != gym.id or branch.status != Branch.Status.ACTIVE
        ):
            raise serializers.ValidationError({'branch_id': 'Branch must be active in this gym.'})
        return attrs

    def create(self, validated_data):
        gym = self.context['gym']
        invited_by = self.context['request'].user
        email = validated_data['email'].lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User(
                email=email,
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                phone=validated_data.get('phone', ''),
                role=validated_data['role'],
            )
            user.set_password(validated_data['password'])
            user.save()
        membership = GymMembership.objects.create(
            user=user,
            gym=gym,
            role=validated_data['role'],
            status=GymMembership.Status.ACTIVE,
            membership_number=validated_data.get('membership_number', ''),
            invited_by=invited_by,
        )
        branch = validated_data.get('branch_id')
        request_branch = getattr(self.context['request'], 'branch', None)
        if branch is None and request_branch is not None and request_branch.gym_id == gym.id:
            branch = request_branch
        if branch is None:
            from .services import primary_branch
            branch = primary_branch(gym)
        if branch:
            membership.branch_memberships.get_or_create(branch=branch)
        if not user.gym_memberships.filter(is_default=True).exists():
            membership.is_default = True
            membership.save(update_fields=['is_default', 'updated_at'])
        if membership.role == GymMembership.Role.MEMBER:
            from apps.members.models import MemberProfile
            profile = MemberProfile._base_manager.filter(user=user, gym=gym).first()
            if profile is None:
                profile = MemberProfile._base_manager.filter(
                    user=user, gym__isnull=True,
                ).first()
            if profile is None:
                MemberProfile._base_manager.create(
                    user=user, gym=gym, branch=branch,
                )
            elif profile.gym_id is None:
                profile.gym = gym
                profile.branch = branch
                profile.save(update_fields=['gym', 'branch', 'updated_at'])
            elif profile.is_deleted:
                # Re-inviting a member revives their trashed profile.
                profile.restore()
        elif membership.role == GymMembership.Role.STAFF:
            from apps.staff.models import StaffProfile
            StaffProfile._base_manager.get_or_create(
                user=user,
                gym=gym,
                defaults={'branch': branch},
            )
        elif membership.role == GymMembership.Role.TRAINER:
            from apps.trainers.models import TrainerProfile
            TrainerProfile._base_manager.get_or_create(
                user=user,
                gym=gym,
                defaults={'branch': branch},
            )
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        if user.role != validated_data['role'] and not user.gym_memberships.exclude(pk=membership.pk).exists():
            user.role = validated_data['role']
            user.save(update_fields=['role'])
        return membership


class InvitationSerializer(serializers.ModelSerializer):
    invitation_url = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = [
            'id', 'gym', 'branch', 'email', 'role', 'status',
            'expires_at', 'invitation_url', 'created_at',
        ]
        read_only_fields = ['id', 'gym', 'status', 'expires_at', 'invitation_url', 'created_at']

    def get_invitation_url(self, obj):
        if not hasattr(obj, 'raw_token'):
            return None
        from django.conf import settings
        base = (getattr(settings, 'FRONTEND_URL', '') or '').rstrip('/')
        if not base:
            request = self.context.get('request')
            base = request.build_absolute_uri('/').rstrip('/') if request else ''
        path = f"/accept-invitation.html?token={obj.raw_token}"
        return f'{base}{path}' if base else path

    def validate(self, attrs):
        gym = self.context['gym']
        branch = attrs.get('branch')
        if branch and (
            branch.gym_id != gym.id
            or branch.status != Branch.Status.ACTIVE
        ):
            raise serializers.ValidationError({'branch': 'Branch must be active in this gym.'})
        request = self.context.get('request')
        if (
            request
            and getattr(request, 'gym_role', request.user.role) == GymMembership.Role.STAFF
            and attrs.get('role') == GymMembership.Role.OWNER
        ):
            raise serializers.ValidationError({'role': 'Staff cannot invite another owner.'})
        return attrs

    def create(self, validated_data):
        invitation, raw_token = Invitation.issue(
            gym=self.context['gym'],
            email=validated_data['email'],
            role=validated_data['role'],
            branch=validated_data.get('branch'),
            invited_by=self.context['request'].user,
        )
        invitation.raw_token = raw_token
        return invitation
