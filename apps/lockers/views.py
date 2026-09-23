from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from apps.accounts.models import User
from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrMemberReadOnly
from .models import Locker, LockerAssignment
from .serializers import LockerSerializer, LockerAssignmentSerializer
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()

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

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        prefix = (request.data.get('prefix') or '').strip()
        start = request.data.get('start')
        end = request.data.get('end')

        # --- Validate range fields ---
        errors = {}
        try:
            start = int(start)
        except (TypeError, ValueError):
            errors['start'] = ['Start must be an integer.']
        try:
            end = int(end)
        except (TypeError, ValueError):
            errors['end'] = ['End must be an integer.']
        if errors:
            raise ValidationError(errors)

        if start < 0:
            raise ValidationError({'start': ['Start must be >= 0.']})
        if end < start:
            raise ValidationError({'end': ['End must be >= start.']})
        count = end - start + 1
        if count > 200:
            raise ValidationError({'end': ['Range cannot exceed 200 lockers.']})

        # --- Validate generated number fits max_length ---
        pad_width = max(len(str(end)), 2)
        max_number_len = Locker.locker_number.field.max_length  # 20
        if len(prefix) + pad_width > max_number_len:
            raise ValidationError({
                'prefix': [f'Prefix + number must fit in {max_number_len} characters. '
                           f'Current: {len(prefix)} + {pad_width} = {len(prefix) + pad_width}.']
            })

        # --- Validate shared fields via serializer ---
        # Use a placeholder locker_number to satisfy the serializer's required
        # field + uniqueness check without colliding with real numbers.
        data = request.data.copy()
        data.setdefault('locker_number', '__bulk_placeholder__')
        ser = LockerSerializer(data=data)
        ser.is_valid(raise_exception=True)
        shared_fields = {
            k: v for k, v in ser.validated_data.items()
            if k != 'locker_number'
        }

        with transaction.atomic():
            # Gather all generated numbers
            numbers = [
                f'{prefix}{str(i).zfill(pad_width)}' for i in range(start, end + 1)
            ]
            # Find existing ones to skip
            existing = set(
                Locker.objects.filter(locker_number__in=numbers)
                .values_list('locker_number', flat=True)
            )
            to_create = [
                Locker(locker_number=num, **shared_fields)
                for num in numbers if num not in existing
            ]
            Locker.objects.bulk_create(to_create)
            skipped = [num for num in numbers if num in existing]

        created_count = len(to_create)
        return Response(
            {
                'created': created_count,
                'skipped': skipped,
                'total_requested': count,
            },
            status=status.HTTP_201_CREATED if created_count else status.HTTP_200_OK,
        )


def _sync_locker_status(locker):
    """Set locker to OCCUPIED if it has any active assignment, else AVAILABLE.

    Does NOT override non-OCCUPIED/AVAILABLE statuses (MAINTENANCE, RESERVED).
    """
    if locker.status not in (Locker.LockerStatus.OCCUPIED, Locker.LockerStatus.AVAILABLE):
        return
    has_active = LockerAssignment.objects.filter(
        locker=locker, is_active=True,
    ).exists()
    new_status = Locker.LockerStatus.OCCUPIED if has_active else Locker.LockerStatus.AVAILABLE
    if locker.status != new_status:
        locker.status = new_status
        locker.save(update_fields=['status'])


class LockerAssignmentViewSet(viewsets.ModelViewSet):
    """Owner/Staff assign lockers to members. Members can view their own assignments."""
    serializer_class = LockerAssignmentSerializer
    permission_classes = [IsOwnerOrStaffOrMemberReadOnly]

    def get_queryset(self):
        self._release_expired_assignments()

        user = self.request.user
        if user.role in (User.Role.OWNER, User.Role.STAFF):
            qs = LockerAssignment.objects.select_related('locker', 'member', 'assigned_by').all()
        else:
            qs = LockerAssignment.objects.select_related('locker', 'member', 'assigned_by').filter(member=user)

        member_id = self.request.query_params.get('member')
        active_only = self.request.query_params.get('active')
        if member_id and user.role in (User.Role.OWNER, User.Role.STAFF):
            qs = qs.filter(member_id=member_id)
        if active_only == 'true':
            qs = qs.filter(is_active=True)
        return qs

    def _release_expired_assignments(self):
        """
        Lazily deactivate any active assignment whose end_date has passed.
        Runs on every list/retrieve so expired rentals don't sit as OCCUPIED
        indefinitely.
        """
        from django.utils import timezone
        today = timezone.now().date()
        expired = LockerAssignment.objects.select_related('locker').filter(
            is_active=True, end_date__isnull=False, end_date__lt=today,
        )
        for assignment in expired:
            assignment.is_active = False
            assignment.save(update_fields=['is_active'])
            _sync_locker_status(assignment.locker)

    def perform_create(self, serializer):
        locker = serializer.validated_data.get('locker')
        member = serializer.validated_data.get('member')

        _sync_locker_status(locker)
        locker.refresh_from_db()

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
        _sync_locker_status(assignment.locker)

    def perform_update(self, serializer):
        with transaction.atomic():
            old_locker = serializer.instance.locker
            was_active = serializer.instance.is_active
            assignment = serializer.save()
            new_locker = assignment.locker

            if old_locker.pk != new_locker.pk:
                _sync_locker_status(old_locker)
                _sync_locker_status(new_locker)
            elif was_active != assignment.is_active:
                _sync_locker_status(new_locker)

    def perform_destroy(self, instance):
        with transaction.atomic():
            locker = instance.locker
            instance.delete()
            _sync_locker_status(locker)