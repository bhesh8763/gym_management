from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.gyms.tenancy import user_has_branch_access

from .models import (
    Exercise,
    WorkoutTemplate,
    WorkoutDay,
    WorkoutDayExercise,
    WorkoutAssignment,
    WorkoutCompletionLog,
    WorkoutTemplateVersion,
)

User = get_user_model()


class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = "__all__"
        read_only_fields = ["created_by"]


class WorkoutDayExerciseSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)
    muscle_group = serializers.CharField(source="exercise.muscle_group", read_only=True)
    video_url = serializers.CharField(source="exercise.video_url", read_only=True)
    exercise_image = serializers.ImageField(source="exercise.image", read_only=True)
    equipment = serializers.CharField(source="exercise.equipment", read_only=True)
    exercise_instructions = serializers.CharField(source="exercise.instructions", read_only=True)

    class Meta:
        model = WorkoutDayExercise
        fields = "__all__"

    def validate(self, attrs):
        request = self.context.get('request')
        day = attrs.get('workout_day', getattr(self.instance, 'workout_day', None))
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None and day and day.template.gym_id != gym.id:
            raise serializers.ValidationError({'workout_day': 'Workout day does not belong to this gym.'})
        branch = getattr(request, 'branch', None) if request else None
        if branch is not None and day and day.template.branch_id not in (None, branch.id):
            raise serializers.ValidationError({'workout_day': 'Workout day does not belong to this branch.'})
        return attrs


class WorkoutDaySerializer(serializers.ModelSerializer):
    exercises = WorkoutDayExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = WorkoutDay
        fields = "__all__"


class WorkoutDayNestedWriteSerializer(serializers.ModelSerializer):
    """
    Optional nested-write variant: lets a trainer POST a full day with its
    exercise list in one call from the "Add Day" flow, instead of two round trips.
    """
    exercises = WorkoutDayExerciseSerializer(many=True, required=False)

    class Meta:
        model = WorkoutDay
        fields = "__all__"

    def validate(self, attrs):
        request = self.context.get('request')
        template = attrs.get('template', getattr(self.instance, 'template', None))
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None and template and template.gym_id != gym.id:
            raise serializers.ValidationError({'template': 'Template does not belong to this gym.'})
        branch = getattr(request, 'branch', None) if request else None
        if branch is not None and template and template.branch_id not in (None, branch.id):
            raise serializers.ValidationError({'template': 'Template does not belong to this branch.'})
        return attrs

    def create(self, validated_data):
        exercises_data = validated_data.pop('exercises', [])
        day = WorkoutDay.objects.create(**validated_data)
        for order, ex_data in enumerate(exercises_data, start=1):
            ex_data.setdefault('order', order)
            WorkoutDayExercise.objects.create(workout_day=day, **ex_data)
        return day


def _get_assigned_member_count(obj):
    """
    List views annotate `assigned_member_count` onto the queryset (one query
    for every row, not one query per row). Single-object responses that don't
    go through that queryset — the reply right after create(), for instance —
    won't have the annotation, so fall back to the model's own live count.
    """
    annotated = getattr(obj, 'assigned_member_count', None)
    return annotated if annotated is not None else obj.get_assigned_member_count()


class WorkoutTemplateSerializer(serializers.ModelSerializer):
    days = WorkoutDaySerializer(many=True, read_only=True)
    assigned_member_count = serializers.SerializerMethodField()
    trainer_name = serializers.CharField(source='trainer.get_full_name', read_only=True)

    # Trainers creating their own templates can omit this — perform_create fills it in.
    # Owners and staff can explicitly assign any trainer by supplying a trainer id.
    trainer = serializers.PrimaryKeyRelatedField(

        queryset=User.objects.all(),
        
        required=False,
        allow_null=True,
    )

    class Meta:
        model = WorkoutTemplate
        fields = "__all__"
        read_only_fields = ["gym", "branch", "status", "reviewed_by"]  # changed only via action endpoints below

    def get_assigned_member_count(self, obj):
        return _get_assigned_member_count(obj)

    def validate(self, data):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        trainer = data.get('trainer', getattr(self.instance, 'trainer', None))
        if request:
            role = getattr(request, 'gym_role', request.user.role)
            if role == 'TRAINER':
                data['trainer'] = request.user
                trainer = request.user
            if gym is not None and trainer is not None:
                from apps.gyms.models import GymMembership
                if not GymMembership.objects.filter(
                    gym=gym, user=trainer, role=GymMembership.Role.TRAINER,
                    status=GymMembership.Status.ACTIVE,
                ).exists():
                    raise serializers.ValidationError({'trainer': 'Trainer is not active in this gym.'})
                if not user_has_branch_access(trainer, gym, getattr(request, 'branch', None)):
                    raise serializers.ValidationError({'trainer': 'Trainer does not have access to this branch.'})
        elif trainer and trainer.role != 'TRAINER':
            raise serializers.ValidationError({'trainer': 'The selected user is not a trainer.'})
        return data


class WorkoutTemplateListSerializer(serializers.ModelSerializer):
    """Lighter payload for the list view — avoids serializing every nested day."""
    assigned_member_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkoutTemplate
        fields = [
            'id', 'gym', 'branch', 'name', 'goal', 'difficulty', 'status',
            'duration_weeks', 'assigned_member_count', 'updated_at',
        ]

    def get_assigned_member_count(self, obj):
        return _get_assigned_member_count(obj)


class WorkoutCompletionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutCompletionLog
        fields = "__all__"
        read_only_fields = ["gym", "branch"]


class WorkoutAssignmentSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    completion_pct = serializers.IntegerField(read_only=True)

    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
    )

    class Meta:
        model = WorkoutAssignment
        fields = "__all__"
        read_only_fields = ["gym", "branch", "assigned_by", "end_date"]

    def validate(self, data):
        template = data.get('template') or getattr(self.instance, 'template', None)
        member = data.get('member', getattr(self.instance, 'member', None))
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        if gym is not None:
            if template and template.gym_id != gym.id:
                raise serializers.ValidationError({'template': 'Template does not belong to this gym.'})
            branch = getattr(request, 'branch', None)
            if branch is not None and template and template.branch_id not in (None, branch.id):
                raise serializers.ValidationError({'template': 'Template does not belong to this branch.'})
            if member is not None:
                from apps.gyms.models import GymMembership
                if not GymMembership.objects.filter(
                    gym=gym, user=member, role=GymMembership.Role.MEMBER,
                    status=GymMembership.Status.ACTIVE,
                ).exists():
                    raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
                if not user_has_branch_access(member, gym, getattr(request, 'branch', None)):
                    raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
        elif member is not None and member.role != 'MEMBER':
            raise serializers.ValidationError({'member': 'The selected user is not a member.'})
        if template and template.status != WorkoutTemplate.Status.APPROVED:
            raise serializers.ValidationError(
                'Only approved templates can be assigned to members.'
            )
        return data

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['assigned_by'] = request.user if request else None
        if request is not None:
            validated_data['gym'] = getattr(request, 'gym', None)
            validated_data['branch'] = getattr(request, 'branch', None)
        return super().create(validated_data)


class WorkoutTemplateVersionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = WorkoutTemplateVersion
        fields = ['id', 'reason', 'created_by_name', 'created_at', 'snapshot']