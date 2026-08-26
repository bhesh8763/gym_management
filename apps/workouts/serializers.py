from django.contrib.auth import get_user_model
from rest_framework import serializers

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

    class Meta:
        model = WorkoutDayExercise
        fields = "__all__"


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

        queryset=User.objects.filter(role='TRAINER'),
        
        required=False,
        allow_null=True,
    )

    class Meta:
        model = WorkoutTemplate
        fields = "__all__"
        read_only_fields = ["status", "reviewed_by"]  # changed only via action endpoints below

    def get_assigned_member_count(self, obj):
        return _get_assigned_member_count(obj)

    def validate(self, data):
        request = self.context.get('request')
        if request and request.user.role == 'TRAINER':
            data['trainer'] = request.user
        return data


class WorkoutTemplateListSerializer(serializers.ModelSerializer):
    """Lighter payload for the list view — avoids serializing every nested day."""
    assigned_member_count = serializers.SerializerMethodField()

    class Meta:
        model = WorkoutTemplate
        fields = [
            'id', 'name', 'goal', 'difficulty', 'status',
            'duration_weeks', 'assigned_member_count', 'updated_at',
        ]

    def get_assigned_member_count(self, obj):
        return _get_assigned_member_count(obj)


class WorkoutCompletionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutCompletionLog
        fields = "__all__"


class WorkoutAssignmentSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    completion_pct = serializers.IntegerField(read_only=True)

    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='MEMBER'),
    )

    class Meta:
        model = WorkoutAssignment
        fields = "__all__"
        read_only_fields = ["assigned_by", "end_date"]

    def validate(self, data):
        template = data.get('template') or getattr(self.instance, 'template', None)
        if template and template.status != WorkoutTemplate.Status.APPROVED:
            raise serializers.ValidationError(
                'Only approved templates can be assigned to members.'
            )
        return data

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['assigned_by'] = request.user if request else None
        return super().create(validated_data)


class WorkoutTemplateVersionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)

    class Meta:
        model = WorkoutTemplateVersion
        fields = ['id', 'reason', 'created_by_name', 'created_at', 'snapshot']