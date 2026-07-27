from rest_framework import serializers
from .models import Attendance


class AttendanceSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    marked_by_name = serializers.CharField(source='marked_by.get_full_name', read_only=True)
    duration_minutes = serializers.ReadOnlyField()
    membership = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'user', 'user_name', 'attendance_type', 'date',
            'status', 'check_in', 'check_out', 'duration_minutes',
            'membership', 'marked_by', 'marked_by_name', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'marked_by']

    def get_membership(self, obj):
        from django.utils import timezone
        membership = obj.user.memberships.filter(
            status='ACTIVE', end_date__gte=timezone.now().date()
        ).order_by('-start_date').first()
        return membership.plan.name if membership else None