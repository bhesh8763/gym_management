"""
Trainer management views.

Endpoints:
    GET    /api/trainers/                  - List all trainers (Owner/Staff)
    POST   /api/trainers/                  - Create trainer profile (Owner only)
    GET    /api/trainers/{id}/             - Get trainer detail (Owner/Staff)
    PUT    /api/trainers/{id}/             - Update trainer profile (Owner only)
    DELETE /api/trainers/{id}/             - Delete trainer profile (Owner only)

    GET    /api/trainers/assignments/      - List assignments (Owner/Staff/Trainer)
    POST   /api/trainers/assignments/      - Create assignment (Owner/Staff only)
    GET    /api/trainers/assignments/{id}/ - Get assignment detail
    PATCH  /api/trainers/assignments/{id}/ - Update assignment (end, deactivate)
    DELETE /api/trainers/assignments/{id}/ - Delete assignment (Owner only)

    GET    /api/trainers/my-members/       - Trainer's own assigned members
"""
from django.contrib.auth import get_user_model
from rest_framework import viewsets, generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwner, IsOwnerOrStaff, IsTrainer, IsOwnerOrStaffOrTrainer
from apps.accounts.permissions import IsOwner, IsOwnerOrStaff, IsTrainer, IsOwnerOrStaffOrTrainer, IsOwnerOrStaffOrTrainerOrMember
from apps.gyms.tenancy import tenant_queryset

from .models import TrainerProfile, TrainerMemberAssignment
from .serializers import (
    TrainerProfileSerializer,
    TrainerProfileCreateSerializer,
    TrainerMemberAssignmentSerializer,
    TrainerMemberAssignmentCreateSerializer,
)

User = get_user_model()


class TrainerProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD for trainer profiles.
    - Owner/Staff can list all.
    - Owner can create/update/delete.
    """
    queryset = TrainerProfile.objects.select_related('user').all()

    def get_queryset(self):
        return tenant_queryset(super().get_queryset(), self.request)

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            permission_classes = [IsOwner]
        else:
            permission_classes = [IsOwnerOrStaff]
        return [p() for p in permission_classes]

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return TrainerProfileCreateSerializer
        return TrainerProfileSerializer

    def perform_create(self, serializer):
        gym = getattr(self.request, 'gym', None)
        user = serializer.validated_data['user']
        if gym is not None and TrainerProfile.objects.filter(gym=gym, user=user).exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'user': 'This user already has a trainer profile in this gym.'})
        serializer.save(gym=gym, branch=getattr(self.request, 'branch', None))

    def perform_destroy(self, instance):
        # Deactivate only this gym membership; the same user may work elsewhere.
        from apps.gyms.models import GymMembership
        GymMembership.objects.filter(
            user=instance.user,
            gym=instance.gym,
            status=GymMembership.Status.ACTIVE,
        ).update(status=GymMembership.Status.INACTIVE)
        instance.delete(user=self.request.user)  # soft delete → trash


class TrainerMemberAssignmentViewSet(viewsets.ModelViewSet):
    """
    CRUD for trainer-member assignments.
    - Owner/Staff can list all and create.
    - Trainers can only see assignments involving them.
    - Owner can delete.
    """
    serializer_class = TrainerMemberAssignmentSerializer

    def get_permissions(self):
      if self.action in ('create',):
        permission_classes = [IsOwnerOrStaff]
      elif self.action in ('destroy',):
        permission_classes = [IsOwner]
      elif self.action in ('update', 'partial_update'):
        permission_classes = [IsOwnerOrStaff]
      else:
        permission_classes = [IsOwnerOrStaffOrTrainerOrMember]   # ← changed this line
      return [p() for p in permission_classes]

    def get_queryset(self):
        user = self.request.user
        qs = tenant_queryset(
            TrainerMemberAssignment.objects.select_related('trainer', 'member').all(),
            self.request,
        )
        role = getattr(self.request, 'gym_role', user.role)
        if role in (User.Role.OWNER, User.Role.STAFF):
            return qs
        if role == User.Role.TRAINER:
            return qs.filter(trainer=user)
        if role == User.Role.MEMBER:
            return qs.filter(member=user)
        return qs.none()

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return TrainerMemberAssignmentCreateSerializer
        return TrainerMemberAssignmentSerializer

    def perform_create(self, serializer):
        assignment = serializer.save()
        from apps.notifications.models import Notification
        Notification.objects.create(
            gym=assignment.gym,
            branch=assignment.branch,
            recipient=assignment.member,
            sender=self.request.user,
            notification_type=Notification.NotificationType.TRAINER_ASSIGNED,
            title='Trainer Assigned',
            message=f'{assignment.trainer.get_full_name()} has been assigned as your trainer.',
        )


    def perform_destroy(self, instance):
        # Soft-deactivate the assignment instead of hard-deleting
        instance.is_active = False
        instance.end_date = instance.assigned_date
        instance.save(update_fields=['is_active', 'end_date'])


class MyAssignedMembersView(APIView):
    """
    GET /api/trainers/my-members/
    Returns the list of members assigned to the current trainer.
    Only accessible by trainers.
    """
    permission_classes = [IsTrainer]

    def get(self, request):
        assignments = tenant_queryset(
            TrainerMemberAssignment.objects.filter(
                trainer=request.user,
                is_active=True,
            ).select_related('member'),
            request,
        )

        members = []
        for assignment in assignments:
            member = assignment.member
            members.append({
                'id': assignment.id,
                'member_id': member.id,
                'member_name': member.get_full_name(),
                'member_email': member.email,
                'member_phone': member.phone,
                'member_display_id': member.display_id,
                'assigned_date': assignment.assigned_date,
                'notes': assignment.notes,
            })

        return Response(members)
