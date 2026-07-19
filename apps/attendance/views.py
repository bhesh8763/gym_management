# attendance views
from rest_framework import viewsets
from apps.accounts.permissions import IsAnyStaffRole
from .models import Attendance
from .serializers import AttendanceSerializer


class AttendanceViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer can record and view attendance.
    Filter with ?date=YYYY-MM-DD, ?user=<id>, ?type=MEMBER|STAFF|TRAINER
    """
    serializer_class = AttendanceSerializer
    permission_classes = [IsAnyStaffRole]

    def get_queryset(self):
        qs = Attendance.objects.select_related('user', 'marked_by').all()
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
        serializer.save(marked_by=self.request.user)