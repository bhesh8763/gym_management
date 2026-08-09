from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q

from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrTrainer

from .models import (
    Exercise,
    WorkoutTemplate,
    WorkoutDay,
    WorkoutDayExercise,
    WorkoutAssignment,
    WorkoutCompletionLog,
)
from .serializers import (
    ExerciseSerializer,
    WorkoutTemplateSerializer,
    WorkoutTemplateListSerializer,
    WorkoutDaySerializer,
    WorkoutDayNestedWriteSerializer,
    WorkoutDayExerciseSerializer,
    WorkoutAssignmentSerializer,
    WorkoutCompletionLogSerializer,
)


# ─── Exercise Library ───────────────────────────────────────────────────────

class ExerciseListCreateView(generics.ListCreateAPIView):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ExerciseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticated]


# ─── Workout Templates ──────────────────────────────────────────────────────

def _visible_templates(user):
    if user.role in ['OWNER', 'STAFF']:
        return WorkoutTemplate.objects.all()
    if user.is_trainer:
        return WorkoutTemplate.objects.filter(trainer=user)
    if user.is_member:
        # Members only ever see templates they've actually been assigned.
        return WorkoutTemplate.objects.filter(
            assignments__member=user, status=WorkoutTemplate.Status.APPROVED
        ).distinct()
    return WorkoutTemplate.objects.none()


class WorkoutTemplateListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        return WorkoutTemplateListSerializer if self.request.method == 'GET' else WorkoutTemplateSerializer

    def get_queryset(self):
        qs = _visible_templates(self.request.user).annotate(
            assigned_member_count=Count(
                'assignments', filter=Q(assignments__status=WorkoutAssignment.Status.ACTIVE), distinct=True
            )
        )
        status_filter = self.request.query_params.get('status')
        difficulty = self.request.query_params.get('difficulty')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if difficulty:
            qs = qs.filter(difficulty=difficulty)
        return qs


class WorkoutTemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkoutTemplateSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        return _visible_templates(self.request.user).annotate(
            assigned_member_count=Count(
                'assignments', filter=Q(assignments__status=WorkoutAssignment.Status.ACTIVE), distinct=True
            )
        )


class WorkoutTemplateSubmitReviewView(APIView):
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk):
        template = _visible_templates(request.user).filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            template.submit_for_review()
        except DjangoValidationError as exc:
            raise DRFValidationError(exc.message)
        return Response(WorkoutTemplateSerializer(template).data)


class WorkoutTemplateApproveView(APIView):
    """Only owners/staff can approve — trainers submit, they don't self-approve."""
    permission_classes = [IsOwnerOrStaff]

    def post(self, request, pk):
        template = WorkoutTemplate.objects.filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            template.approve(reviewer=request.user)
        except DjangoValidationError as exc:
            raise DRFValidationError(exc.message)
        return Response(WorkoutTemplateSerializer(template).data)


class WorkoutTemplateArchiveView(APIView):
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk):
        template = _visible_templates(request.user).filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        template.archive()
        return Response(WorkoutTemplateSerializer(template).data)


class WorkoutTemplateDuplicateView(APIView):
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk):
        template = _visible_templates(request.user).filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        clone = template.clone(new_name=request.data.get('name'))
        return Response(WorkoutTemplateSerializer(clone).data, status=status.HTTP_201_CREATED)


# ─── Workout Days / Exercises (builder) ─────────────────────────────────────

class WorkoutDayListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkoutDayNestedWriteSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        qs = WorkoutDay.objects.all()
        template_id = self.request.query_params.get('template')
        return qs.filter(template_id=template_id) if template_id else qs


class WorkoutDayDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkoutDay.objects.all()
    serializer_class = WorkoutDaySerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


class WorkoutDayExerciseListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkoutDayExerciseSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        qs = WorkoutDayExercise.objects.all()
        day_id = self.request.query_params.get('workout_day')
        return qs.filter(workout_day_id=day_id) if day_id else qs


class WorkoutDayExerciseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkoutDayExercise.objects.all()
    serializer_class = WorkoutDayExerciseSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


# ─── Assignments ────────────────────────────────────────────────────────────

def _visible_assignments(user):
    if user.role in ['OWNER', 'STAFF']:
        return WorkoutAssignment.objects.all()
    if user.is_trainer:
        return WorkoutAssignment.objects.filter(template__trainer=user)
    if user.is_member:
        return WorkoutAssignment.objects.filter(member=user)
    return WorkoutAssignment.objects.none()


class WorkoutAssignmentListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkoutAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = _visible_assignments(self.request.user)
        template_id = self.request.query_params.get('template')
        if template_id:
            qs = qs.filter(template_id=template_id)
        return qs


class WorkoutAssignmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkoutAssignmentSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        return _visible_assignments(self.request.user)


# ─── Completion logs (member-facing progress) ───────────────────────────────

class WorkoutCompletionLogListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkoutCompletionLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = WorkoutCompletionLog.objects.filter(
            assignment__in=_visible_assignments(self.request.user)
        )
        assignment_id = self.request.query_params.get('assignment')
        return qs.filter(assignment_id=assignment_id) if assignment_id else qs

    def perform_create(self, serializer):
        assignment = serializer.validated_data['assignment']
        if self.request.user.is_member and assignment.member_id != self.request.user.id:
            raise PermissionDenied('Members can only log their own workouts.')
        serializer.save()