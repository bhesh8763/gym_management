from rest_framework import serializers
from .models import Locker, LockerAssignment


class LockerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Locker
        fields = [
            'id', 'locker_number', 'location', 'status',
            'monthly_fee', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class LockerAssignmentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    locker_number = serializers.CharField(source='locker.locker_number', read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)

    class Meta:
        model = LockerAssignment
        fields = [
            'id', 'locker', 'locker_number', 'member', 'member_name',
            'start_date', 'end_date', 'is_active',
            'assigned_by', 'assigned_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'assigned_by', 'created_at']