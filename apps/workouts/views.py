from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrTrainer

from .models import (
    Exercise,
    WorkoutTemplate,
    WorkoutDay,
    WorkoutDayExercise,
    WorkoutAssignment,
    WorkoutCompletionLog,
    WorkoutTemplateVersion,
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
    WorkoutTemplateVersionSerializer,
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
        # Explicit order_by: annotate() combined with a filtered Count() can
        # leave the queryset's ordering ambiguous even with Meta.ordering set,
        # which makes DRF's pagination warn (and, worse, can actually
        # duplicate or skip rows across pages). Pin it here.
        qs = _visible_templates(self.request.user).annotate(
            assigned_member_count=Count(
                'assignments', filter=Q(assignments__status=WorkoutAssignment.Status.ACTIVE), distinct=True
            )
        ).order_by('-updated_at')
        status_filter = self.request.query_params.get('status')
        difficulty = self.request.query_params.get('difficulty')
        search = self.request.query_params.get('search')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if difficulty:
            qs = qs.filter(difficulty=difficulty)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(goal__icontains=search))
        return qs


class WorkoutTemplateDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkoutTemplateSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        return _visible_templates(self.request.user).annotate(
            assigned_member_count=Count(
                'assignments', filter=Q(assignments__status=WorkoutAssignment.Status.ACTIVE), distinct=True
            )
        ).order_by('-updated_at')


class WorkoutTemplateSubmitReviewView(APIView):
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk):
        template = _visible_templates(request.user).filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            template.submit_for_review(actor=request.user)
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


class WorkoutTemplateVersionListView(generics.ListAPIView):
    serializer_class = WorkoutTemplateVersionSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        template = _visible_templates(self.request.user).filter(pk=self.kwargs['pk']).first()
        if not template:
            return WorkoutTemplateVersion.objects.none()
        return template.versions.all()


class WorkoutTemplateVersionRestoreView(APIView):
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk, version_id):
        template = _visible_templates(request.user).filter(pk=pk).first()
        if not template:
            return Response(status=status.HTTP_404_NOT_FOUND)
        version = template.versions.filter(pk=version_id).first()
        if not version:
            return Response(status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            restored = version.restore()
        return Response(WorkoutTemplateSerializer(restored).data)


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


class WorkoutDayMoveView(APIView):
    """
    Swap this day's position with the adjacent day in the same week.
    Two PATCHes from the frontend swapping day_number directly would risk
    the (template, week_number, day_number) unique constraint firing on the
    intermediate state — do the swap through a temporary sentinel instead,
    inside one transaction, so it's atomic either way.
    """
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def post(self, request, pk):
        direction = request.data.get('direction')
        if direction not in ('up', 'down'):
            raise DRFValidationError({'direction': 'Must be "up" or "down".'})

        day = WorkoutDay.objects.filter(pk=pk).first()
        if not day:
            return Response(status=status.HTTP_404_NOT_FOUND)

        siblings = WorkoutDay.objects.filter(
            template=day.template, week_number=day.week_number
        ).order_by('day_number')
        siblings_list = list(siblings)
        idx = next((i for i, d in enumerate(siblings_list) if d.id == day.id), None)
        if idx is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        swap_idx = idx - 1 if direction == 'up' else idx + 1
        if swap_idx < 0 or swap_idx >= len(siblings_list):
            raise DRFValidationError({'direction': f'Already at the {"top" if direction == "up" else "bottom"}.'})

        other = siblings_list[swap_idx]
        with transaction.atomic():
            day_number_a, day_number_b = day.day_number, other.day_number
            # Route through a value neither row currently holds, so neither
            # UPDATE ever collides with the unique_together mid-swap.
            sentinel = max(d.day_number for d in siblings_list) + 1000
            WorkoutDay.objects.filter(pk=day.pk).update(day_number=sentinel)
            WorkoutDay.objects.filter(pk=other.pk).update(day_number=day_number_a)
            WorkoutDay.objects.filter(pk=day.pk).update(day_number=day_number_b)

        return Response(WorkoutTemplateSerializer(day.template).data)


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
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        # The DB has a partial unique constraint (one ACTIVE assignment per
        # template+member) that catches races the serializer's validate()
        # can't — two trainers assigning the same member in the same instant
        # can both pass validation before either commits. Without this,
        # the loser of that race gets an unhandled IntegrityError -> 500.
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise DRFValidationError(
                {'member': 'This member already has an active assignment for this template.'}
            )


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