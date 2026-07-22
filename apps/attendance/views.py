# attendance views
from django.contrib.auth import get_user_model
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsAnyStaffRole
from .models import Attendance
from .serializers import AttendanceSerializer

User = get_user_model()

# Roles that can record/view attendance for *anyone*.
STAFF_SIDE_ROLES = (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER)


class AttendanceViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer can record and view attendance for anyone.
    Members can check themselves in/out (create/update their own record only)
    and can only ever see their own attendance history.

    Filter with ?date=YYYY-MM-DD, ?user=<id>, ?type=MEMBER|STAFF|TRAINER
    """
    serializer_class = AttendanceSerializer

    def get_permissions(self):
        # Deleting attendance records stays a staff-side-only action.
        if self.action == 'destroy':
            return [IsAnyStaffRole()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Attendance.objects.select_related('user', 'marked_by').all()

        user = self.request.user
        if user.role not in STAFF_SIDE_ROLES:
            # Members (and any other non-staff-side role) only ever see
            # their own attendance — they can't browse everyone else's.
            qs = qs.filter(user=user)

        date = self.request.query_params.get('date')
        user_id = self.request.query_params.get('user')
        att_type = self.request.query_params.get('type')
        if date:
            qs = qs.filter(date=date)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if att_type:
            qs = qs.filter(attendance_type=att_type)
        return qs

    def perform_create(self, serializer):
        requester = self.request.user
        target_user = serializer.validated_data.get('user')

        if requester.role not in STAFF_SIDE_ROLES and target_user != requester:
            raise PermissionDenied('You can only record your own attendance.')

        serializer.save(marked_by=requester)

    def perform_update(self, serializer):
        requester = self.request.user
        instance = self.get_object()

        if requester.role not in STAFF_SIDE_ROLES and instance.user != requester:
            raise PermissionDenied('You can only update your own attendance.')

        serializer.save()
