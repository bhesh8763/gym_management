from rest_framework import serializers

from .models import ProgressEntry, PersonalRecord


class ProgressEntrySerializer(serializers.ModelSerializer):
    bmi = serializers.ReadOnlyField()
    member = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = ProgressEntry
        fields = "__all__"
        read_only_fields = ["recorded_by"]


class PersonalRecordSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)
    member = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = PersonalRecord
        fields = "__all__"