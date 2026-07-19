from rest_framework import serializers
from .models import Equipment, MaintenanceRecord


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = [
            'id', 'name', 'category', 'brand', 'model_number', 'serial_number',
            'quantity', 'purchase_date', 'purchase_price', 'condition',
            'location', 'image', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MaintenanceRecordSerializer(serializers.ModelSerializer):
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.get_full_name', read_only=True)

    class Meta:
        model = MaintenanceRecord
        fields = [
            'id', 'equipment', 'equipment_name', 'maintenance_type', 'status',
            'scheduled_date', 'completed_date', 'performed_by', 'cost',
            'description', 'next_maintenance_date',
            'recorded_by', 'recorded_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'recorded_by', 'created_at', 'updated_at']