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

    def perform_destroy(self, instance):
        # Soft-delete: deactivate the user instead of hard-deleting
        user = instance.user
        user.is_active = False
        user.save(update_fields=['is_active'])
        instance.delete()


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
            permission_classes = [IsOwnerOrStaffOrTrainer]
        return [p() for p in permission_classes]

    def get_queryset(self):
        user = self.request.user
        if user.role in (User.Role.OWNER, User.Role.STAFF):
            return TrainerMemberAssignment.objects.select_related(
                'trainer', 'member',
            ).all()
        elif user.role == User.Role.TRAINER:
            return TrainerMemberAssignment.objects.select_related(
                'trainer', 'member',
            ).filter(trainer=user)
        return TrainerMemberAssignment.objects.none()

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return TrainerMemberAssignmentCreateSerializer
        return TrainerMemberAssignmentSerializer

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
        assignments = TrainerMemberAssignment.objects.filter(
            trainer=request.user,
            is_active=True,
        ).select_related('member')

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
