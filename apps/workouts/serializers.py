from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import Exercise, WorkoutPlan, WorkoutDay, WorkoutDayExercise

User = get_user_model()


class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = "__all__"
        read_only_fields = ["created_by"]


class WorkoutDayExerciseSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)

    class Meta:
        model = WorkoutDayExercise
        fields = "__all__"


class WorkoutDaySerializer(serializers.ModelSerializer):
    exercises = WorkoutDayExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = WorkoutDay
        fields = "__all__"


class WorkoutPlanSerializer(serializers.ModelSerializer):
    days = WorkoutDaySerializer(many=True, read_only=True)
    # Trainers creating their own plans can omit this — perform_create fills it in.
    # Owners and staff can explicitly assign any trainer by supplying a trainer id.
    trainer = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='TRAINER'),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = WorkoutPlan
        fields = "__all__"

    def validate(self, data):
        request = self.context.get('request')
        # Trainers always author their own plans
        if request and request.user.role == 'TRAINER':
            data['trainer'] = request.user
        return data