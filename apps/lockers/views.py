from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from apps.accounts.permissions import IsOwnerOrStaff
from .models import Locker, LockerAssignment
from .serializers import LockerSerializer, LockerAssignmentSerializer


class LockerViewSet(viewsets.ModelViewSet):
    """Owner/Staff manage the physical locker inventory."""
    serializer_class = LockerSerializer
    permission_classes = [IsOwnerOrStaff]
    queryset = Locker.objects.all()

    def get_queryset(self):
        qs = Locker.objects.all()
        status_ = self.request.query_params.get('status')
        if status_:
            qs = qs.filter(status=status_)
        return qs


class LockerAssignmentViewSet(viewsets.ModelViewSet):
    """Owner/Staff assign lockers to members."""
    serializer_class = LockerAssignmentSerializer
    permission_classes = [IsOwnerOrStaff]

    def get_queryset(self):
        qs = LockerAssignment.objects.select_related('locker', 'member', 'assigned_by').all()
        member_id = self.request.query_params.get('member')
        active_only = self.request.query_params.get('active')
        if member_id:
            qs = qs.filter(member_id=member_id)
        if active_only == 'true':
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        locker = serializer.validated_data.get('locker')
        member = serializer.validated_data.get('member')

        if locker.status != Locker.LockerStatus.AVAILABLE:
            raise ValidationError(
                {'locker': f'Locker {locker.locker_number} is not available '
                           f'(status: {locker.get_status_display()}).'}
            )
        if LockerAssignment.objects.filter(member=member, is_active=True).exists():
            raise ValidationError(
                {'member': 'This member already has an active locker assignment.'}
            )

        assignment = serializer.save(assigned_by=self.request.user)
        # Auto-flip the locker's status to OCCUPIED when assigned
        assignment.locker.status = Locker.LockerStatus.OCCUPIED
        assignment.locker.save(update_fields=['status'])

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        assignment = serializer.save()
        # If the assignment just got deactivated (e.g. member gave up the
        # locker), free the locker back up so it can be assigned again.
        if was_active and not assignment.is_active:
            assignment.locker.status = Locker.LockerStatus.AVAILABLE
            assignment.locker.save(update_fields=['status'])