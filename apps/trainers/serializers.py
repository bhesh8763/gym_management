"""
Serializers for trainer profiles and trainer-member assignments.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from apps.gyms.tenancy import user_has_branch_access

from .models import TrainerProfile, TrainerMemberAssignment

User = get_user_model()


class TrainerProfileSerializer(serializers.ModelSerializer):
    """Read serializer for trainer profiles with user info."""
    full_name = serializers.SerializerMethodField()
    email = serializers.CharField(source='user.email', read_only=True)
    display_id = serializers.CharField(source='user.display_id', read_only=True)
    assigned_members_count = serializers.SerializerMethodField()

    class Meta:
        model = TrainerProfile
        fields = [
            'id', 'gym', 'branch', 'user', 'full_name', 'email', 'display_id',
            'specializations', 'certifications', 'experience_years',
            'bio', 'joined_date', 'salary', 'is_available',
            'assigned_members_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['gym', 'branch', 'created_at', 'updated_at']

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    def get_assigned_members_count(self, obj):
        assignments = obj.user.trainer_assignments.filter(
            gym=obj.gym, is_active=True,
        )
        request = self.context.get('request')
        branch = getattr(request, 'branch', None) if request is not None else obj.branch
        if branch is not None:
            assignments = assignments.filter(
                Q(branch=branch) | Q(branch__isnull=True)
            )
        return assignments.count()


class TrainerProfileCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating/updating trainer profiles."""
    # Accept user_id as input
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
    )

    class Meta:
        model = TrainerProfile
        fields = [
            'id', 'user', 'gym', 'specializations', 'certifications',
            'experience_years', 'bio', 'joined_date', 'salary', 'is_available',
        ]
        read_only_fields = ['id', 'gym']

    def validate_user(self, value):
        if self.instance and value != self.instance.user:
            raise serializers.ValidationError('The trainer profile user cannot be changed.')
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None:
            from apps.gyms.models import GymMembership
            if not GymMembership.objects.filter(
                gym=gym,
                user=value,
                role=GymMembership.Role.TRAINER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError('User is not an active trainer in this gym.')
            if not user_has_branch_access(value, gym, getattr(request, 'branch', None)):
                raise serializers.ValidationError('User does not have access to this branch.')
        elif value.role != User.Role.TRAINER:
            raise serializers.ValidationError('The selected user is not a trainer.')
        # Include soft-deleted profiles: the DB unique (gym, user) slot is
        # still taken, so report it as a duplicate rather than 500-ing.
        duplicate = TrainerProfile._base_manager.filter(user=value, gym=gym)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError('This user already has a trainer profile in this gym.')
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['gym'] = getattr(request, 'gym', None)
        validated_data['branch'] = getattr(request, 'branch', None)
        return super().create(validated_data)


class TrainerMemberAssignmentSerializer(serializers.ModelSerializer):
    """Read serializer for trainer-member assignments."""
    trainer_name = serializers.SerializerMethodField()
    trainer_display_id = serializers.SerializerMethodField()
    member_name = serializers.SerializerMethodField()
    member_display_id = serializers.SerializerMethodField()

    class Meta:
        model = TrainerMemberAssignment
        fields = [
            'id', 'gym', 'branch', 'trainer', 'trainer_name', 'trainer_display_id',
            'member', 'member_name', 'member_display_id',
            'assigned_date', 'end_date', 'is_active', 'notes', 'created_at',
        ]
        read_only_fields = ['gym', 'branch', 'assigned_date', 'created_at']

    def get_trainer_name(self, obj):
        return obj.trainer.get_full_name()

    def get_trainer_display_id(self, obj):
        return obj.trainer.display_id

    def get_member_name(self, obj):
        return obj.member.get_full_name()

    def get_member_display_id(self, obj):
        return obj.member.display_id


class TrainerMemberAssignmentCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating trainer-member assignments."""
    trainer = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
    )
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
    )

    class Meta:
        model = TrainerMemberAssignment
        fields = ['id', 'gym', 'branch', 'trainer', 'member', 'end_date', 'notes']
        read_only_fields = ['id', 'gym', 'branch']

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['gym'] = getattr(request, 'gym', None)
        validated_data['branch'] = getattr(request, 'branch', None)
        return super().create(validated_data)

    def validate(self, attrs):
        trainer = attrs.get('trainer', getattr(self.instance, 'trainer', None))
        member = attrs.get('member', getattr(self.instance, 'member', None))
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None:
            from apps.gyms.models import GymMembership
            if trainer is not None and not GymMembership.objects.filter(
                gym=gym, user=trainer, role=GymMembership.Role.TRAINER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'trainer': 'Trainer is not active in this gym.'})
            if member is not None and not GymMembership.objects.filter(
                gym=gym, user=member, role=GymMembership.Role.MEMBER,
                status=GymMembership.Status.ACTIVE,
            ).exists():
                raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
            branch = getattr(request, 'branch', None)
            if trainer is not None and not user_has_branch_access(trainer, gym, branch):
                raise serializers.ValidationError({'trainer': 'Trainer does not have access to this branch.'})
            if member is not None and not user_has_branch_access(member, gym, branch):
                raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
        elif (
            (trainer is not None and trainer.role != User.Role.TRAINER)
            or (member is not None and member.role != User.Role.MEMBER)
        ):
            raise serializers.ValidationError('Trainer and member roles are required.')

        if trainer is not None and member is not None:
            existing = TrainerMemberAssignment.objects.filter(
                trainer=trainer, member=member, is_active=True,
            ).exclude(pk=getattr(self, 'instance', None) and self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {'member': 'This member is already assigned to this trainer.'}
                )
        return attrs
