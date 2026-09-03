from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
import csv
from datetime import date

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
from apps.notifications.models import Notification, MessageGroup, GroupMessage, PinnedConversation
from apps.progress.models import PersonalRecord
from django.contrib.auth import get_user_model

User = get_user_model()


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
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method in ('PUT', 'PATCH', 'DELETE'):
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

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
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method in ('PUT', 'PATCH', 'DELETE'):
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

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
        log = serializer.save()

        # Auto-detect Personal Records — only for exercises that have weight in set_logs
        if log.set_logs and self.request.user.is_member:
            workout_day = log.workout_day
            exercises = workout_day.exercises.select_related('exercise').all()
            # Only check exercises that are configured as weighted (have weight_kg set)
            weighted_exercises = [wde for wde in exercises if wde.weight_kg is not None]
            for wde in weighted_exercises:
                exercise = wde.exercise
                # Find the best weight logged for this exercise from set_logs
                best_weight = None
                best_reps = None
                for s in log.set_logs:
                    if 'weight' in s and s['weight'] is not None:
                        w = float(s['weight'])
                        if w > 0 and (best_weight is None or w > float(best_weight)):
                            best_weight = s['weight']
                            best_reps = s.get('reps')
                if best_weight is None:
                    continue
                pr, created = PersonalRecord.objects.get_or_create(
                    member=self.request.user,
                    exercise=exercise,
                    defaults={
                        'value': best_weight,
                        'unit': 'kg',
                        'date': log.date,
                        'best_weight_kg': best_weight,
                        'best_reps': best_reps,
                        'assignment': assignment,
                        'log': log,
                    },
                )
                if not created:
                    if best_weight is not None and (pr.best_weight_kg is None or float(best_weight) > float(pr.best_weight_kg)):
                        pr.best_weight_kg = best_weight
                        pr.best_reps = best_reps
                        pr.value = best_weight
                        pr.date = log.date
                        pr.assignment = assignment
                        pr.log = log
                        pr.save()


# ─── Member self-service actions (pause / resume / cancel) ──────────────────

class AssignmentPauseView(APIView):
    """Member pauses their own active assignment."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        assignment = WorkoutAssignment.objects.filter(pk=pk, member=request.user).first()
        if not assignment:
            return Response({'detail': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
        if assignment.status != WorkoutAssignment.Status.ACTIVE:
            return Response({'detail': 'Only active assignments can be paused.'}, status=status.HTTP_400_BAD_REQUEST)
        assignment.status = WorkoutAssignment.Status.PAUSED
        assignment.save(update_fields=['status', 'updated_at'])
        return Response(WorkoutAssignmentSerializer(assignment).data)


class AssignmentResumeView(APIView):
    """Member resumes their own paused assignment."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        assignment = WorkoutAssignment.objects.filter(pk=pk, member=request.user).first()
        if not assignment:
            return Response({'detail': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
        if assignment.status != WorkoutAssignment.Status.PAUSED:
            return Response({'detail': 'Only paused assignments can be resumed.'}, status=status.HTTP_400_BAD_REQUEST)
        assignment.status = WorkoutAssignment.Status.ACTIVE
        assignment.save(update_fields=['status', 'updated_at'])
        return Response(WorkoutAssignmentSerializer(assignment).data)


class AssignmentCancelView(APIView):
    """Member cancels their own active or paused assignment."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        assignment = WorkoutAssignment.objects.filter(pk=pk, member=request.user).first()
        if not assignment:
            return Response({'detail': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
        if assignment.status not in (WorkoutAssignment.Status.ACTIVE, WorkoutAssignment.Status.PAUSED):
            return Response({'detail': 'Only active or paused assignments can be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        assignment.status = WorkoutAssignment.Status.CANCELLED
        assignment.save(update_fields=['status', 'updated_at'])
        return Response(WorkoutAssignmentSerializer(assignment).data)


# ─── Trainer messaging (via notifications) ──────────────────────────────────

class TrainerMessageView(APIView):
    """Member sends a message to their trainer via the notification system."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_member:
            return Response({'detail': 'Only members can message trainers.'}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        # Find the trainer from the member's most recent active assignment
        assignment = WorkoutAssignment.objects.filter(
            member=request.user,
            status__in=[WorkoutAssignment.Status.ACTIVE, WorkoutAssignment.Status.PAUSED],
        ).select_related('template', 'template__trainer').order_by('-created_at').first()

        if not assignment or not assignment.template or not assignment.template.trainer:
            return Response({'detail': 'No trainer assigned to you yet.'}, status=status.HTTP_400_BAD_REQUEST)

        trainer = assignment.template.trainer
        Notification.objects.create(
            recipient=trainer,
            notification_type=Notification.NotificationType.MEMBER_MESSAGE,
            title=f'Message from {request.user.get_full_name() or request.user.email}',
            message=message[:500],
            related_membership_id=request.user.id,
        )
        return Response({'detail': 'Message sent to your trainer.'}, status=status.HTTP_201_CREATED)


# ─── Trainer Messages Inbox + Reply ────────────────────────────────────────


def _serialize_notification(n):
    """Serialize a notification for the messages inbox API."""
    # Sender name is embedded in the title (e.g. "Message from Jane Doe" /
    # "Reply from Jane Doe") — strip whichever prefix is present.
    title = n.title or ''
    sender = title
    for prefix in ('Message from ', 'Reply from '):
        if title.startswith(prefix):
            sender = title[len(prefix):]
            break
    return {
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'is_read': n.is_read,
        'read_at': n.read_at,
        'created_at': n.created_at,
        'sender_name': sender,
        'sender_id': n.related_membership_id,
        'recipient_id': n.recipient_id,
        'recipient_name': (
            n.recipient.get_full_name() or n.recipient.email
        ) if n.recipient_id else None,
        'notification_type': n.notification_type,
        'is_edited': n.is_edited,
    }


class TrainerMessagesView(APIView):
    """Trainer views all member messages and replies sent via the messaging feature."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member_id = request.query_params.get('member_id')

        if request.user.is_member:
            # Members see their own sent messages and replies they received
            member_name = request.user.get_full_name() or request.user.email
            qs = Notification.objects.filter(
                Q(
                    notification_type=Notification.NotificationType.MEMBER_MESSAGE,
                    related_membership_id=request.user.id,
                )
                |
                Q(
                    notification_type=Notification.NotificationType.TRAINER_REPLY,
                    recipient=request.user,
                ),
            ).order_by('created_at')

            # Optionally filter by a specific trainer
            trainer_id = request.query_params.get('trainer_id')
            if trainer_id:
                qs = qs.filter(
                    Q(related_membership_id=request.user.id, recipient_id=trainer_id)
                    | Q(recipient=request.user, related_membership_id=trainer_id)
                )
        else:
            # Trainers/owners/staff see messages sent to them and their replies
            qs = Notification.objects.filter(
                Q(
                    recipient=request.user,
                    notification_type=Notification.NotificationType.MEMBER_MESSAGE,
                )
                |
                Q(
                    notification_type=Notification.NotificationType.TRAINER_REPLY,
                    related_membership_id=request.user.id,
                ),
            ).order_by('created_at')

            # Filter by a specific member if provided
            if member_id:
                qs = qs.filter(
                    Q(related_membership_id=member_id, recipient=request.user)
                    | Q(recipient_id=member_id, related_membership_id=request.user.id)
                )

        unread_only = request.query_params.get('is_read')
        if unread_only is not None:
            qs = qs.filter(is_read=unread_only.lower() in ('true', '1', 'yes'))

        items = list(qs)
        return Response([_serialize_notification(n) for n in items])


class TrainerReplyView(APIView):
    """Trainer replies to a member's message."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in ('TRAINER', 'OWNER', 'STAFF'):
            return Response(
                {'detail': 'Only trainers, owners, and staff can reply.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        reply_text = request.data.get('message', '').strip()
        if not reply_text:
            return Response({'detail': 'Reply cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        member_id = request.data.get('member_id')
        if not member_id:
            return Response({'detail': 'member_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve the member user
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            member = User.objects.get(pk=member_id)
        except User.DoesNotExist:
            return Response({'detail': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not member.is_member:
            return Response({'detail': 'Target user is not a member.'}, status=status.HTTP_400_BAD_REQUEST)

        # Create a TRAINER_REPLY notification for the member
        trainer_name = request.user.get_full_name() or request.user.email
        Notification.objects.create(
            recipient=member,
            notification_type=Notification.NotificationType.TRAINER_REPLY,
            title=f'Reply from {trainer_name}',
            message=reply_text[:500],
            related_membership_id=request.user.id,
        )
        return Response({'detail': 'Reply sent.'}, status=status.HTTP_201_CREATED)


# ─── Direct messaging between any allowed roles ──────────────────────────────

def _assigned_member_ids(user):
    """IDs of members assigned to a trainer (active or paused assignments)."""
    return set(
        WorkoutAssignment.objects.filter(
            template__trainer=user,
            status__in=[WorkoutAssignment.Status.ACTIVE, WorkoutAssignment.Status.PAUSED],
        ).values_list('member_id', flat=True)
    )


def _assigned_trainer(user):
    """The trainer currently assigned to a member (via their most recent assignment)."""
    assignment = WorkoutAssignment.objects.filter(
        member=user,
        status__in=[WorkoutAssignment.Status.ACTIVE, WorkoutAssignment.Status.PAUSED],
    ).select_related('template', 'template__trainer').order_by('-created_at').first()
    if assignment and assignment.template and assignment.template.trainer:
        return assignment.template.trainer
    return None


def _owner_started_conversation(member, owner):
    """
    True when the owner has already messaged this member. A member may only
    *continue* a conversation with the owner — they can never start one.
    """
    return Notification.objects.filter(
        recipient=member,
        related_membership_id=owner.pk,
        notification_type__in=[
            Notification.NotificationType.MEMBER_MESSAGE,
            Notification.NotificationType.TRAINER_REPLY,
        ],
    ).exists()


def _can_direct_message(user, target):
    """
    Who may start a 1-on-1 chat with whom:
      - Owner: anyone
      - Staff: anyone (including the owner, per product rule)
      - Trainer: their assigned members + staff
      - Member: their assigned trainer + staff, and the owner ONLY if the
        owner already started the conversation (members can continue, not
        initiate, a chat with the owner)
    """
    if user.pk == target.pk:
        return False
    if user.is_owner:
        return True
    if user.is_gym_staff:
        return True
    if user.is_trainer:
        if target.role == User.Role.STAFF:
            return True
        if target.role == User.Role.MEMBER:
            return target.pk in _assigned_member_ids(user)
        return False
    if user.is_member:
        if target.role == User.Role.STAFF:
            return True
        if target.role == User.Role.TRAINER:
            trainer = _assigned_trainer(user)
            return trainer is not None and trainer.pk == target.pk
        if target.role == User.Role.OWNER:
            return _owner_started_conversation(user, target)
        return False
    return False


def _allowed_recipients(user):
    """Active users this person is allowed to open a 1-on-1 chat with."""
    if user.is_owner or user.is_gym_staff:
        return User.objects.filter(is_active=True).exclude(pk=user.pk)
    if user.is_trainer:
        member_ids = _assigned_member_ids(user)
        return User.objects.filter(is_active=True).filter(
            Q(role=User.Role.STAFF) | Q(pk__in=member_ids)
        ).exclude(pk=user.pk)
    if user.is_member:
        trainer = _assigned_trainer(user)
        qs = User.objects.filter(is_active=True).filter(role=User.Role.STAFF)
        if trainer:
            qs = qs | User.objects.filter(pk=trainer.pk)
        # The owner is never offered as a "new message" option to members.
        # If the owner starts a conversation, the member continues it from the
        # existing conversation in their list — not from this picker.
        return qs.exclude(pk=user.pk).distinct()
    return User.objects.none()


def _can_create_group(user):
    return user.role in (User.Role.TRAINER, User.Role.STAFF, User.Role.OWNER)


def _group_allowed_member_ids(user):
    """Users that may be added to a group created by `user`:
      - Owner: anyone
      - Staff: anyone except the owner
      - Trainer: only their assigned members
    """
    if user.is_owner:
        return set(User.objects.filter(is_active=True).values_list('pk', flat=True))
    if user.is_gym_staff:
        return set(User.objects.filter(is_active=True).exclude(role=User.Role.OWNER).values_list('pk', flat=True))
    if user.is_trainer:
        return _assigned_member_ids(user)
    return set()


class DirectMessageView(APIView):
    """Send a 1-on-1 message to any user the sender is allowed to message."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        recipient_id = request.data.get('recipient_id')
        if not recipient_id:
            return Response({'detail': 'recipient_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            recipient = User.objects.get(pk=recipient_id, is_active=True)
        except User.DoesNotExist:
            return Response({'detail': 'Recipient not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _can_direct_message(request.user, recipient):
            return Response(
                {'detail': 'You are not allowed to message this user.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        sender = request.user
        sender_name = sender.get_full_name() or sender.email
        if sender.is_member:
            n_type = Notification.NotificationType.MEMBER_MESSAGE
            title = f'Message from {sender_name}'
        else:
            n_type = Notification.NotificationType.TRAINER_REPLY
            title = f'Reply from {sender_name}' if recipient.is_member else f'Message from {sender_name}'

        n = Notification.objects.create(
            recipient=recipient,
            notification_type=n_type,
            title=title,
            message=message[:500],
            related_membership_id=sender.pk,
        )
        return Response(
            {'detail': 'Message sent.', 'id': n.pk},
            status=status.HTTP_201_CREATED,
        )


class MessageRecipientsView(APIView):
    """Users the current user may message. ?purpose=group applies group rules."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        purpose = request.query_params.get('purpose')
        if purpose == 'group':
            if not _can_create_group(request.user):
                return Response([], status=status.HTTP_200_OK)
            user_ids = _group_allowed_member_ids(request.user)
            qs = User.objects.filter(pk__in=user_ids, is_active=True)
        else:
            qs = _allowed_recipients(request.user)
        qs = qs.order_by('first_name', 'last_name')
        return Response([
            {
                'user_id': u.pk,
                'full_name': u.get_full_name() or u.email,
                'role': u.role,
            }
            for u in qs
        ])


# ─── Group chats ─────────────────────────────────────────────────────────────

class MessageGroupListCreateView(APIView):
    """List groups the user belongs to, or create a new group."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = MessageGroup.objects.filter(members=request.user).prefetch_related('members')
        data = []
        for g in groups:
            last = g.messages.order_by('-created_at').first()
            unread = g.messages.exclude(sender=request.user).exclude(read_by=request.user).count()
            data.append({
                'id': g.pk,
                'name': g.name,
                'created_by_id': g.created_by_id,
                'member_ids': list(g.members.values_list('pk', flat=True)),
                'member_names': {
                    str(m.pk): (m.get_full_name() or m.email)
                    for m in g.members.all()
                },
                'last_message': last.message if last else None,
                'last_sender_id': last.sender_id if last else None,
                'last_sender_name': (
                    last.sender.get_full_name() or last.sender.email
                ) if last else None,
                'last_created_at': last.created_at if last else None,
                'unread_count': unread,
            })
        return Response(data)

    def post(self, request):
        if not _can_create_group(request.user):
            return Response(
                {'detail': 'You are not allowed to create groups.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'detail': 'Group name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        member_ids = request.data.get('member_ids') or []
        if not isinstance(member_ids, list) or not member_ids:
            return Response(
                {'detail': 'Add at least one member.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            member_ids = [int(i) for i in member_ids]
        except (TypeError, ValueError):
            return Response(
                {'detail': 'Invalid member_ids.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed = _group_allowed_member_ids(request.user)
        if any(i not in allowed for i in member_ids):
            return Response(
                {'detail': 'One or more members cannot be added to this group.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            group = MessageGroup.objects.create(name=name, created_by=request.user)
            group.members.add(request.user)
            group.members.add(*member_ids)
        return Response({'id': group.pk, 'name': group.name, 'detail': 'Group created.'}, status=status.HTTP_201_CREATED)


class MessageGroupDetailView(APIView):
    """List messages inside a group (members only)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        group = MessageGroup.objects.filter(pk=pk, members=request.user).first()
        if not group:
            return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)
        msgs = group.messages.select_related('sender').order_by('created_at')
        return Response([
            {
                'id': m.pk,
                'sender_id': m.sender_id,
                'sender_name': m.sender.get_full_name() or m.sender.email,
                'message': m.message,
                'is_edited': m.is_edited,
                'created_at': m.created_at,
                'is_read': m.read_by.filter(pk=request.user.pk).exists(),
            }
            for m in msgs
        ])


class MessageGroupSendView(APIView):
    """Send a message to a group the user belongs to."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = MessageGroup.objects.filter(pk=pk, members=request.user).first()
        if not group:
            return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)
        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        msg = GroupMessage.objects.create(group=group, sender=request.user, message=message[:500])
        msg.read_by.add(request.user)  # the sender has read their own message
        return Response({'id': msg.pk, 'detail': 'Sent.'}, status=status.HTTP_201_CREATED)


class MessageGroupMarkReadView(APIView):
    """Mark all unread messages in a group as read for the current user."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        group = MessageGroup.objects.filter(pk=pk, members=request.user).first()
        if not group:
            return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)
        unread = group.messages.exclude(sender=request.user).exclude(read_by=request.user)
        for m in unread:
            m.read_by.add(request.user)
        return Response({'detail': 'Marked as read.'}, status=status.HTTP_200_OK)


# ─── Edit / delete messages + pin conversations ──────────────────────────────

class DirectMessageDetailView(APIView):
    """Edit or delete one of the current user's own direct messages."""
    permission_classes = [IsAuthenticated]

    def _get_own(self, request, pk):
        """The sender may only edit/delete their own chat message."""
        n = Notification.objects.filter(pk=pk).first()
        if not n:
            return None
        if n.notification_type not in (
            Notification.NotificationType.MEMBER_MESSAGE,
            Notification.NotificationType.TRAINER_REPLY,
        ):
            return None
        if n.related_membership_id != request.user.pk:
            return None
        return n

    def patch(self, request, pk):
        n = self._get_own(request, pk)
        if not n:
            return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        n.message = message[:500]
        n.is_edited = True
        n.save(update_fields=['message', 'is_edited'])
        return Response({'detail': 'Message updated.', 'is_edited': True}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        n = self._get_own(request, pk)
        if not n:
            return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
        n.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupMessageDetailView(APIView):
    """Edit or delete one of the current user's own messages inside a group."""
    permission_classes = [IsAuthenticated]

    def _get_own(self, request, group_pk, message_pk):
        group = MessageGroup.objects.filter(pk=group_pk, members=request.user).first()
        if not group:
            return None, None
        msg = GroupMessage.objects.filter(
            pk=message_pk, group=group, sender=request.user
        ).first()
        return group, msg

    def patch(self, request, group_pk, message_pk):
        group, msg = self._get_own(request, group_pk, message_pk)
        if not msg:
            return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
        message = request.data.get('message', '').strip()
        if not message:
            return Response({'detail': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
        msg.message = message[:500]
        msg.is_edited = True
        msg.save(update_fields=['message', 'is_edited'])
        return Response({'detail': 'Message updated.', 'is_edited': True}, status=status.HTTP_200_OK)

    def delete(self, request, group_pk, message_pk):
        group, msg = self._get_own(request, group_pk, message_pk)
        if not msg:
            return Response({'detail': 'Message not found.'}, status=status.HTTP_404_NOT_FOUND)
        msg.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessagePinView(APIView):
    """Pin/unpin conversations for the current user.
    GET returns pins; POST pins; DELETE unpins (by query params).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pins = PinnedConversation.objects.filter(user=request.user)
        return Response([{'kind': p.kind, 'target_id': p.target_id} for p in pins])

    def post(self, request):
        kind = request.data.get('kind')
        target_id = request.data.get('target_id')
        if kind not in ('direct', 'group'):
            return Response({'detail': 'Invalid kind.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return Response({'detail': 'Invalid target_id.'}, status=status.HTTP_400_BAD_REQUEST)
        if kind == 'group':
            if not MessageGroup.objects.filter(pk=target_id, members=request.user).exists():
                return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if target_id == request.user.pk:
                return Response({'detail': 'Invalid target.'}, status=status.HTTP_400_BAD_REQUEST)
            if not User.objects.filter(pk=target_id, is_active=True).exists():
                return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        PinnedConversation.objects.get_or_create(user=request.user, kind=kind, target_id=target_id)
        return Response({'detail': 'Pinned.'}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        PinnedConversation.objects.filter(
            user=request.user,
            kind=request.query_params.get('kind'),
            target_id=request.query_params.get('target_id'),
        ).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationDeleteView(APIView):
    """Delete an entire conversation (direct or group) for the current user."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        kind = request.query_params.get('kind')
        target_id = request.query_params.get('target_id')

        if kind not in ('direct', 'group'):
            return Response({'detail': 'Invalid kind.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            return Response({'detail': 'Invalid target_id.'}, status=status.HTTP_400_BAD_REQUEST)

        if kind == 'direct':
            # Delete all direct messages between the current user and the target user
            if target_id == request.user.pk:
                return Response({'detail': 'Invalid target.'}, status=status.HTTP_400_BAD_REQUEST)
            if not User.objects.filter(pk=target_id, is_active=True).exists():
                return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Delete messages sent by current user to target
            Notification.objects.filter(
                recipient_id=target_id,
                related_membership_id=request.user.pk,
                notification_type__in=[
                    Notification.NotificationType.MEMBER_MESSAGE,
                    Notification.NotificationType.TRAINER_REPLY,
                ],
            ).delete()

            # Delete messages sent by target to current user
            Notification.objects.filter(
                recipient_id=request.user.pk,
                related_membership_id=target_id,
                notification_type__in=[
                    Notification.NotificationType.MEMBER_MESSAGE,
                    Notification.NotificationType.TRAINER_REPLY,
                ],
            ).delete()

            # Also delete any pin for this conversation
            PinnedConversation.objects.filter(
                user=request.user, kind='direct', target_id=target_id
            ).delete()

        else:  # group
            group = MessageGroup.objects.filter(pk=target_id).first()
            if not group:
                return Response({'detail': 'Group not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Only the creator, owner, or staff can delete a group
            is_creator = group.created_by_id == request.user.pk
            is_admin = request.user.role in ('OWNER', 'STAFF')
            if not is_creator and not is_admin:
                return Response(
                    {'detail': 'Only the group creator or admin can delete a group.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Delete the group and all its messages (CASCADE handles GroupMessage)
            group.delete()

            # Also delete any pin for this group
            PinnedConversation.objects.filter(
                user=request.user, kind='group', target_id=target_id
            ).delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── CSV Export ─────────────────────────────────────────────────────────────

class WorkoutCompletionLogExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logs = WorkoutCompletionLog.objects.filter(
            assignment__in=_visible_assignments(request.user)
        ).select_related('assignment', 'assignment__template', 'workout_day')

        # Apply same filters as the list view
        assignment_id = request.query_params.get('assignment')
        if assignment_id:
            logs = logs.filter(assignment_id=assignment_id)

        response = HttpResponse(content_type='text/csv')
        today = date.today().isoformat()
        response['Content-Disposition'] = f'attachment; filename="fitcore-workouts-{today}.csv"'

        writer = csv.writer(response)
        writer.writerow(['Date', 'Program', 'Day', 'Status', 'Duration (min)', 'Calories', 'Difficulty', 'Pain', 'Notes'])

        for log in logs:
            day_name = ''
            tpl_name = ''
            if log.workout_day:
                day_name = log.workout_day.day_name or f'Day {log.workout_day.day_number}'
            if log.assignment and log.assignment.template:
                tpl_name = log.assignment.template.name

            writer.writerow([
                log.date,
                tpl_name,
                day_name,
                log.status,
                log.duration_minutes or '',
                log.calories or '',
                log.perceived_difficulty or '',
                log.pain_level or '',
                log.notes or '',
            ])

        return response