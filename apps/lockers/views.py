from rest_framework import viewsets
from apps.accounts.permissions import IsOwnerOrStaff
from .models import Locker, LockerAssignment


class LockerViewSet(viewsets.ModelViewSet):
    """Owner/Staff manage the physical locker inventory."""
    from .serializers import LockerSerializer
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
    from .serializers import LockerAssignmentSerializer
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
        assignment = serializer.save(assigned_by=self.request.user)
        # Auto-flip the locker's status to OCCUPIED when assigned
        assignment.locker.status = Locker.LockerStatus.OCCUPIED
        assignment.locker.save(update_fields=['status'])