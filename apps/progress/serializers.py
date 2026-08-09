from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import ProgressEntry, PersonalRecord

User = get_user_model()


class ProgressEntrySerializer(serializers.ModelSerializer):
    bmi = serializers.ReadOnlyField()
    # Allow staff/owner to record on behalf of any member by supplying member id.
    # Members recording their own data can omit it — perform_create fills it in.
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='MEMBER'),
        required=False,
    )

    class Meta:
        model = ProgressEntry
        fields = "__all__"
        read_only_fields = ["recorded_by"]

    def validate(self, data):
        request = self.context.get('request')
        # Members can only log for themselves
        if request and request.user.role == 'MEMBER':
            data['member'] = request.user
        return data


class PersonalRecordSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)
    # Same pattern: writable for staff/owner, auto-filled for members
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='MEMBER'),
        required=False,
    )

    class Meta:
        model = PersonalRecord
        fields = "__all__"

    def validate(self, data):
        request = self.context.get('request')
        if request and request.user.role == 'MEMBER':
            data['member'] = request.user
        return data