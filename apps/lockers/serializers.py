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

    def validate_status(self, value):
        if value == Locker.LockerStatus.OCCUPIED and self.instance and self.instance.status != Locker.LockerStatus.OCCUPIED:
            raise serializers.ValidationError(
                'Cannot set status to OCCUPIED directly. '
                'Create a locker assignment instead.'
            )
        return value


class LockerAssignmentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.get_full_name', read_only=True)
    locker_number = serializers.CharField(source='locker.locker_number', read_only=True)
    locker_location = serializers.CharField(source='locker.location', read_only=True)
    monthly_fee = serializers.DecimalField(source='locker.monthly_fee', max_digits=8, decimal_places=2, read_only=True)
    assigned_by_name = serializers.CharField(source='assigned_by.get_full_name', read_only=True)

    class Meta:
        model = LockerAssignment
        fields = [
            'id', 'locker', 'locker_number', 'locker_location', 'monthly_fee',
            'member', 'member_name',
            'start_date', 'end_date', 'is_active',
            'assigned_by', 'assigned_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'assigned_by', 'created_at']