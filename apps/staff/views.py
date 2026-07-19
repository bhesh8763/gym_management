from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.accounts.permissions import IsOwnerOrStaff, IsAnyStaffRole
from .models import StaffProfile, LeaveRequest
from .serializers import StaffProfileSerializer, LeaveRequestSerializer


class StaffProfileViewSet(viewsets.ModelViewSet):
    """Owner/Staff manage staff profiles."""
    serializer_class = StaffProfileSerializer
    permission_classes = [IsOwnerOrStaff]
    queryset = StaffProfile.objects.select_related('user').all()


class LeaveRequestViewSet(viewsets.ModelViewSet):
    """
    Any staff-side role can submit and view leave requests.
    Only Owner/Staff can approve or reject (via the /review/ action).
    """
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAnyStaffRole]

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related('requester', 'reviewed_by').all()
        # Non-owner/staff only see their own requests
        if self.request.user.role not in ('OWNER', 'STAFF'):
            qs = qs.filter(requester=self.request.user)
        return qs

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsOwnerOrStaff])
    def review(self, request, pk=None):
        """POST /api/staff/leave-requests/{id}/review/  body: {"status": "APPROVED"|"REJECTED", "review_note": "..."}"""
        leave = self.get_object()
        new_status = request.data.get('status')
        if new_status not in ('APPROVED', 'REJECTED'):
            return Response({'error': 'status must be APPROVED or REJECTED'}, status=status.HTTP_400_BAD_REQUEST)
        leave.status = new_status
        leave.review_note = request.data.get('review_note', '')
        leave.reviewed_by = request.user
        leave.save()
        return Response(LeaveRequestSerializer(leave).data)