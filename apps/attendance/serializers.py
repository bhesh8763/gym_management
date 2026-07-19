from rest_framework import serializers
from .models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    marked_by_name = serializers.CharField(source='marked_by.get_full_name', read_only=True)
    duration_minutes = serializers.ReadOnlyField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'user', 'user_name', 'attendance_type', 'date',
            'check_in', 'check_out', 'duration_minutes',
            'marked_by', 'marked_by_name', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'marked_by']