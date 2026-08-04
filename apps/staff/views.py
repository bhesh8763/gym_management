from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.accounts.permissions import IsOwnerOrStaff, IsAnyStaffRole
from .models import StaffProfile, LeaveRequest
from .serializers import StaffProfileSerializer, StaffCreateSerializer, LeaveRequestSerializer


class StaffProfileViewSet(viewsets.ModelViewSet):
    """Owner/Staff manage staff profiles."""
    serializer_class = StaffProfileSerializer
    permission_classes = [IsOwnerOrStaff]
    queryset = StaffProfile.objects.select_related('user').all()

    def get_serializer_class(self):
        if self.action == 'create':
            return StaffCreateSerializer
        return StaffProfileSerializer

    def create(self, request, *args, **kwargs):
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(
            StaffProfileSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """POST /api/staff/profiles/{id}/activate/ — re-enable a staff user's login."""
        profile = self.get_object()
        profile.user.is_active = True
        profile.user.save(update_fields=['is_active'])
        return Response(StaffProfileSerializer(profile).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """POST /api/staff/profiles/{id}/deactivate/ — disable a staff user's login."""
        profile = self.get_object()
        profile.user.is_active = False
        profile.user.save(update_fields=['is_active'])
        return Response(StaffProfileSerializer(profile).data)

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """POST /api/staff/profiles/{id}/reset-password/  body: {"new_password": "..."}
        Owner-side reset — sets a new password for the staff member's login."""
        profile = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password:
            return Response(
                {'new_password': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new_password, user=profile.user)
        except DjangoValidationError as e:
            return Response({'new_password': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        profile.user.set_password(new_password)
        profile.user.save(update_fields=['password'])
        return Response({'detail': 'Password reset successfully.'})


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

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """POST /api/staff/leave-requests/{id}/cancel/  — requester cancels their own pending request."""
        leave = self.get_object()
        if leave.requester != request.user:
            return Response({'error': 'You can only cancel your own leave requests.'}, status=status.HTTP_403_FORBIDDEN)
        if leave.status != 'PENDING':
            return Response({'error': 'Only pending requests can be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        leave.status = 'CANCELLED'
        leave.save()
        return Response(LeaveRequestSerializer(leave).data)