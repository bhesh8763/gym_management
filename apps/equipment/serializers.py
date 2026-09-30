from rest_framework import serializers
from .models import Equipment, MaintenanceRecord


class EquipmentSerializer(serializers.ModelSerializer):
    serial_number = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=100,
    )

    class Meta:
        model = Equipment
        fields = [
            'id', 'gym', 'branch', 'name', 'category', 'brand', 'model_number', 'serial_number',
            'quantity', 'purchase_date', 'purchase_price', 'condition',
            'location', 'image', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'created_at', 'updated_at']

    def validate(self, data):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        serial = data.get('serial_number', getattr(self.instance, 'serial_number', None))
        if serial:
            lookup = {'serial_number': serial}
            lookup['gym_id'] = gym.id if gym is not None else None
            qs = Equipment._base_manager.filter(**lookup)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'serial_number': 'This serial number is already used in this gym.'})
        return data


class MaintenanceRecordSerializer(serializers.ModelSerializer):
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)

    class Meta:
        model = MaintenanceRecord
        fields = [
            'id', 'gym', 'branch', 'equipment', 'equipment_name', 'maintenance_type', 'status',
            'scheduled_date', 'completed_date', 'performed_by', 'cost',
            'description', 'next_maintenance_date',
            'recorded_by', 'recorded_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'gym', 'branch', 'recorded_by', 'created_at', 'updated_at']

    def validate(self, data):
        request = self.context.get('request')
        gym = getattr(request, 'gym', None) if request else None
        equipment = data.get('equipment', getattr(self.instance, 'equipment', None))
        if gym is not None and equipment and equipment.gym_id != gym.id:
            raise serializers.ValidationError({'equipment': 'Equipment does not belong to this gym.'})
        branch = getattr(request, 'branch', None) if request else None
        if branch is not None and equipment and equipment.branch_id not in (None, branch.id):
            raise serializers.ValidationError({'equipment': 'Equipment does not belong to this branch.'})
        return data