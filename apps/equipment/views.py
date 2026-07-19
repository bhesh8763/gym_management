from rest_framework import viewsets
from apps.accounts.permissions import IsOwnerOrStaff
from .models import Equipment, MaintenanceRecord
from .serializers import EquipmentSerializer, MaintenanceRecordSerializer


class EquipmentViewSet(viewsets.ModelViewSet):
    """Owner/Staff manage equipment inventory."""
    serializer_class = EquipmentSerializer
    permission_classes = [IsOwnerOrStaff]

    def get_queryset(self):
        qs = Equipment.objects.all()
        category = self.request.query_params.get('category')
        condition = self.request.query_params.get('condition')
        if category:
            qs = qs.filter(category=category)
        if condition:
            qs = qs.filter(condition=condition)
        return qs


class MaintenanceRecordViewSet(viewsets.ModelViewSet):
    """Owner/Staff schedule and log maintenance."""
    serializer_class = MaintenanceRecordSerializer
    permission_classes = [IsOwnerOrStaff]

    def get_queryset(self):
        qs = MaintenanceRecord.objects.select_related('equipment', 'recorded_by').all()
        equipment_id = self.request.query_params.get('equipment')
        status_ = self.request.query_params.get('status')
        if equipment_id:
            qs = qs.filter(equipment_id=equipment_id)
        if status_:
            qs = qs.filter(status=status_)
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)