from rest_framework import serializers
from .models import StaffProfile, LeaveRequest


class StaffProfileSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = StaffProfile
        fields = [
            'id', 'user', 'user_name', 'user_email', 'department',
            'designation', 'joined_date', 'salary', 'id_document',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class LeaveRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.CharField(source='requester.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    duration_days = serializers.ReadOnlyField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'requester', 'requester_name', 'leave_type',
            'start_date', 'end_date', 'duration_days', 'reason', 'status',
            'reviewed_by', 'reviewed_by_name', 'review_note', 'created_at',
        ]
        read_only_fields = ['id', 'requester', 'status', 'reviewed_by', 'created_at']