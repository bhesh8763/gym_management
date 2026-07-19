from rest_framework import serializers

from .models import Exercise, WorkoutPlan, WorkoutDay, WorkoutDayExercise


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
    trainer = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = WorkoutPlan
        fields = "__all__"