from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from apps.accounts.models import User
from apps.accounts.permissions import (
    IsOwner, IsOwnerOrStaff, IsAnyStaffRole,
    _subscription_allowed, _tenant_allowed,
)
from apps.gyms.tenancy import tenant_queryset
from .models import StaffProfile, LeaveRequest, Shift, StaffShift
from .serializers import (
    StaffProfileSerializer, StaffCreateSerializer, LeaveRequestSerializer,
    ShiftSerializer, StaffShiftSerializer, BulkStaffShiftSerializer,
)


class IsOwnerOrAdminWrite(BasePermission):
    """Owner/Admin: full write access.
    Other staff roles (STAFF/TRAINER): read-only."""

    message = 'Write access is restricted to owners and admins.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not _tenant_allowed(request) or not _subscription_allowed(request):
            return False
        role = getattr(request, 'gym_role', None) or request.user.role
        if request.method in SAFE_METHODS:
            return role in (
                User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER, User.Role.ADMIN,
            )
        return role in (User.Role.OWNER, User.Role.ADMIN)


class StaffProfileViewSet(viewsets.ModelViewSet):
    """Owner manages staff profiles; staff (receptionists) can list/view trainers."""
    serializer_class = StaffProfileSerializer
    permission_classes = [IsOwnerOrStaff]
    queryset = StaffProfile.objects.select_related('user').all()

    def get_queryset(self):
        return tenant_queryset(super().get_queryset(), self.request)

    def get_serializer_class(self):
        if self.action == 'create':
            if self.request and 'user' in self.request.data:
                return StaffProfileSerializer
            return StaffCreateSerializer
        return StaffProfileSerializer

    def create(self, request, *args, **kwargs):
        if 'user' in request.data:
            serializer = StaffProfileSerializer(data=request.data, context={'request': request})
        else:
            serializer = StaffCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(
            gym=getattr(request, 'gym', None),
            branch=getattr(request, 'branch', None),
        )
        return Response(
            StaffProfileSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        """Handle User-owned fields (email, phone, profile_picture) before serializer validates."""
        partial = kwargs.get('partial', False)
        profile = self.get_object()
        user = profile.user
        user_fields_updated = []

        # profile_picture lives on User
        if 'profile_picture' in request.FILES:
            user.profile_picture = request.FILES['profile_picture']
            user_fields_updated.append('profile_picture')

        # email lives on User
        if 'email' in request.data and request.data['email'] != user.email:
            user.email = request.data['email']
            user_fields_updated.append('email')

        # user_phone lives on User
        if 'user_phone' in request.data:
            new_phone = request.data['user_phone']
            if new_phone != user.phone:
                user.phone = new_phone
                user_fields_updated.append('phone')

        if user_fields_updated:
            user.save(update_fields=user_fields_updated)

        # Remove User-only fields from request data so serializer doesn't choke
        mutable_data = request.data.copy() if hasattr(request.data, 'copy') else request.data
        for field in ('email', 'user_phone', 'profile_picture'):
            mutable_data.pop(field, None)

        serializer = self.get_serializer(profile, data=mutable_data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(StaffProfileSerializer(profile, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """POST /api/staff/profiles/{id}/activate/ — re-enable a staff user's login."""
        profile = self.get_object()
        from apps.gyms.models import GymMembership
        if getattr(request, 'gym', None) is not None:
            GymMembership.objects.filter(
                user=profile.user, gym=getattr(request, 'gym', None), status=GymMembership.Status.INACTIVE,
            ).update(status=GymMembership.Status.ACTIVE)
            if not profile.user.is_active:
                profile.user.is_active = True
                profile.user.save(update_fields=['is_active'])
        else:
            profile.user.is_active = True
            profile.user.save(update_fields=['is_active'])
        return Response(StaffProfileSerializer(profile).data)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """POST /api/staff/profiles/{id}/deactivate/ — disable a staff user's login."""
        profile = self.get_object()
        from apps.gyms.models import GymMembership
        if getattr(request, 'gym', None) is not None:
            GymMembership.objects.filter(
                user=profile.user, gym=getattr(request, 'gym', None), status=GymMembership.Status.ACTIVE,
            ).update(status=GymMembership.Status.INACTIVE)
            if not profile.user.gym_memberships.filter(
                status=GymMembership.Status.ACTIVE,
            ).exists():
                profile.user.is_active = False
                profile.user.save(update_fields=['is_active'])
        else:
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
        from django.utils import timezone as _tz
        # Auto-reject expired pending leaves before any query
        _today = _tz.now().date()
        stale_qs = tenant_queryset(
            LeaveRequest.objects.filter(
                status=LeaveRequest.LeaveStatus.PENDING,
                end_date__lt=_today,
            ),
            self.request,
        )
        stale_qs.update(
            status=LeaveRequest.LeaveStatus.REJECTED,
            review_note='Auto-rejected: leave end date passed without review.',
        )

        qs = tenant_queryset(
            LeaveRequest.objects.select_related('requester', 'reviewed_by').all(),
            self.request,
        )
        if getattr(self.request, 'gym_role', self.request.user.role) == 'OWNER':
            pass  # Owners see all
        elif getattr(self.request, 'gym_role', self.request.user.role) == 'STAFF':
            # Receptionists only see leave requests from trainers in this gym.
            from apps.gyms.models import GymMembership
            qs = qs.filter(
                requester__gym_memberships__gym=self.request.gym,
                requester__gym_memberships__role=GymMembership.Role.TRAINER,
                requester__gym_memberships__status=GymMembership.Status.ACTIVE,
            ) if getattr(self.request, 'gym', None) is not None else qs.filter(
                requester__role=GymMembership.Role.TRAINER,
            )
        else:
            # Trainers only see their own requests
            qs = qs.filter(requester=self.request.user)

        # Support ?status=PENDING etc. (no django-filter installed)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        return qs

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(
            requester=self.request.user,
            gym=getattr(self.request, 'gym', None),
            branch=getattr(self.request, 'branch', None),
        )

    def perform_update(self, serializer):
        """Only the requester can edit their own PENDING leave request."""
        leave = self.get_object()
        if leave.requester != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only edit your own leave requests.')
        if leave.status != 'PENDING':
            from rest_framework.exceptions import ValidationError
            raise ValidationError('Only pending leave requests can be edited.')
        serializer.save()

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


class ShiftViewSet(viewsets.ModelViewSet):
    """CRUD for fixed shift templates.
    Owner/Admin write; authenticated staff roles read."""
    serializer_class = ShiftSerializer
    permission_classes = [IsOwnerOrAdminWrite]
    queryset = Shift.objects.all()


class StaffShiftViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Weekly schedule assignments (list/create/delete only).

    Owner/Admin write and see everyone's rows; STAFF/TRAINER read only
    their own. Filters: ?staff=, ?weekday=, ?shift=.
    """
    serializer_class = StaffShiftSerializer
    permission_classes = [IsOwnerOrAdminWrite]

    def get_queryset(self):
        qs = StaffShift.objects.select_related('staff', 'shift').order_by(
            'weekday', 'shift__start_time', 'staff__last_name',
        )
        role = getattr(self.request, 'gym_role', None) or self.request.user.role
        if role not in (User.Role.OWNER, User.Role.ADMIN):
            qs = qs.filter(staff=self.request.user)

        params = self.request.query_params
        staff_id = self._int_param(params, 'staff')
        if staff_id is not None:
            qs = qs.filter(staff_id=staff_id)
        weekday = self._int_param(params, 'weekday')
        if weekday is not None:
            if not 0 <= weekday <= 6:
                raise ValidationError(
                    {'weekday': 'Must be between 0 (Monday) and 6 (Sunday).'}
                )
            qs = qs.filter(weekday=weekday)
        shift_id = self._int_param(params, 'shift')
        if shift_id is not None:
            qs = qs.filter(shift_id=shift_id)
        return qs

    @staticmethod
    def _int_param(params, name):
        raw = params.get(name)
        if raw in (None, ''):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValidationError({name: 'Must be an integer.'})

    @action(detail=False, methods=['post'], url_path='bulk-set')
    def bulk_set(self, request):
        """POST /api/staff/schedules/bulk-set/
        body: {staff, assignments: [{weekday, shift_ids: [...]}]}
        Atomically replaces that person's entire weekly schedule."""
        serializer = BulkStaffShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        staff = serializer.validated_data['staff']
        assignments = serializer.validated_data['assignments']

        with transaction.atomic():
            StaffShift.objects.filter(staff=staff).delete()
            new_rows = [
                StaffShift(staff=staff, shift_id=shift_id, weekday=entry['weekday'])
                for entry in assignments
                for shift_id in entry['shift_ids']
            ]
            StaffShift.objects.bulk_create(new_rows)

        schedule = StaffShift.objects.filter(staff=staff).select_related('shift')
        return Response(
            {
                'staff': staff.id,
                'created': len(new_rows),
                'schedule': StaffShiftSerializer(schedule, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=['get'], url_path='roster')
    def roster(self, request):
        """GET /api/staff/schedules/roster/ — the whole week grouped
        weekday -> shift -> staff."""
        qs = StaffShift.objects.select_related('staff', 'shift').order_by(
            'weekday', 'shift__start_time', 'staff__last_name',
        )
        grouped = {day: {} for day in range(7)}
        for row in qs:
            slot = grouped[row.weekday].get(row.shift_id)
            if slot is None:
                slot = {
                    'shift': row.shift_id,
                    'name': row.shift.name,
                    'start_time': row.shift.start_time,
                    'end_time': row.shift.end_time,
                    'staff': [],
                }
                grouped[row.weekday][row.shift_id] = slot
            slot['staff'].append(
                {
                    'id': row.staff_id,
                    'name': row.staff.get_full_name(),
                    'display_id': row.staff.display_id,
                    'role': row.staff.role,
                }
            )
        week = [
            {
                'weekday': day,
                'weekday_display': StaffShift.Weekday(day).label,
                'shifts': list(grouped[day].values()),
            }
            for day in range(7)
        ]
        return Response({'week': week})