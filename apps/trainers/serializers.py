"""
Serializers for trainer profiles and trainer-member assignments.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

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
            'id', 'user', 'full_name', 'email', 'display_id',
            'specializations', 'certifications', 'experience_years',
            'bio', 'joined_date', 'salary', 'is_available',
            'assigned_members_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_full_name(self, obj):
        return obj.user.get_full_name()

    def get_assigned_members_count(self, obj):
        return obj.user.trainer_assignments.filter(is_active=True).count()


class TrainerProfileCreateSerializer(serializers.ModelSerializer):
    """Write serializer for creating/updating trainer profiles."""
    # Accept user_id as input
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.TRAINER),
    )

    class Meta:
        model = TrainerProfile
        fields = [
            'id', 'user', 'specializations', 'certifications',
            'experience_years', 'bio', 'joined_date', 'salary', 'is_available',
        ]
        read_only_fields = ['id']


class TrainerMemberAssignmentSerializer(serializers.ModelSerializer):
    """Read serializer for trainer-member assignments."""
    trainer_name = serializers.SerializerMethodField()
    trainer_display_id = serializers.SerializerMethodField()
    member_name = serializers.SerializerMethodField()
    member_display_id = serializers.SerializerMethodField()

    class Meta:
        model = TrainerMemberAssignment
        fields = [
            'id', 'trainer', 'trainer_name', 'trainer_display_id',
            'member', 'member_name', 'member_display_id',
            'assigned_date', 'end_date', 'is_active', 'notes', 'created_at',
        ]
        read_only_fields = ['assigned_date', 'created_at']

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
        queryset=User.objects.filter(role=User.Role.TRAINER),
    )
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.MEMBER),
    )

    class Meta:
        model = TrainerMemberAssignment
        fields = ['id', 'trainer', 'member', 'end_date', 'notes']
        read_only_fields = ['id']

    def validate(self, attrs):
        trainer = attrs.get('trainer')
        member = attrs.get('member')

        # Check if member already has an active assignment with this trainer
        existing = TrainerMemberAssignment.objects.filter(
            trainer=trainer, member=member, is_active=True,
        ).exclude(pk=getattr(self, 'instance', None) and self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(
                {'member': 'This member is already assigned to this trainer.'}
            )
        return attrs
