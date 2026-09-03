"""
Tests for the Workouts app API.

Run with:
    python manage.py test apps.workouts.tests

Coverage:
    - Trainers cannot self-approve their own templates (owner/staff only)
    - A template must be Approved before it can be assigned
    - Duplicate active assignment (same member + template) is rejected, not a 500
    - Members only ever see templates they've actually been assigned
    - Duplicate() produces an independent Draft copy, not a shared reference
"""
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.workouts.models import WorkoutTemplate, WorkoutAssignment, WorkoutDay
from apps.notifications.models import Notification

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class WorkoutAPITestCase(APITestCase):
    def get_future_date(self, days=1):
        return timezone.now().date() + timedelta(days=days)
        
    def get_future_date_str(self, days=1):
        return self.get_future_date(days).strftime('%Y-%m-%d')


class WorkoutTemplateApprovalTestCase(WorkoutAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.template = WorkoutTemplate.objects.create(
            name='Push Pull Legs', trainer=self.trainer, duration_weeks=6,
        )

    def test_trainer_can_submit_own_template_for_review(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/submit-review/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, WorkoutTemplate.Status.IN_REVIEW)

    def test_trainer_cannot_approve_own_template(self):
        self.template.status = WorkoutTemplate.Status.IN_REVIEW
        self.template.save()
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/approve/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, WorkoutTemplate.Status.IN_REVIEW)

    def test_owner_can_approve_template_in_review(self):
        self.template.status = WorkoutTemplate.Status.IN_REVIEW
        self.template.save()
        self.client.force_authenticate(self.owner)
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/approve/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, WorkoutTemplate.Status.APPROVED)
        self.assertEqual(self.template.reviewed_by, self.owner)

    def test_cannot_approve_a_draft_directly(self):
        """Skipping the review step entirely shouldn't be possible via the API."""
        self.client.force_authenticate(self.owner)
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/approve/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_trainer_cannot_see_another_trainers_draft(self):
        self.client.force_authenticate(self.other_trainer)
        r = self.client.get(f'/api/workouts/templates/{self.template.id}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class WorkoutAssignmentTestCase(WorkoutAPITestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user('owner2@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer3@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)
        self.draft_template = WorkoutTemplate.objects.create(
            name='Draft Plan', trainer=self.trainer, duration_weeks=4,
        )
        self.approved_template = WorkoutTemplate.objects.create(
            name='Approved Plan', trainer=self.trainer, duration_weeks=4,
            status=WorkoutTemplate.Status.APPROVED,
        )

    def test_cannot_assign_a_draft_template(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post('/api/workouts/assignments/', {
            'template': self.draft_template.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(1),
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_assign_an_approved_template(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post('/api/workouts/assignments/', {
            'template': self.approved_template.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(1),
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(WorkoutAssignment.objects.count(), 1)

    def test_duplicate_active_assignment_is_rejected_not_500(self):
        """The DB has a partial unique constraint for this — confirm the API
        surfaces it as a clean 400, not an unhandled IntegrityError."""
        WorkoutAssignment.objects.create(
            template=self.approved_template, member=self.member,
            status=WorkoutAssignment.Status.ACTIVE, start_date=self.get_future_date(0),
        )
        self.client.force_authenticate(self.trainer)
        r = self.client.post('/api/workouts/assignments/', {
            'template': self.approved_template.id, 'member': self.member.id,
            'start_date': self.get_future_date_str(1),
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WorkoutAssignment.objects.filter(
            template=self.approved_template, member=self.member
        ).count(), 1)

    def test_member_only_sees_own_assignments(self):
        WorkoutAssignment.objects.create(
            template=self.approved_template, member=self.member,
            status=WorkoutAssignment.Status.ACTIVE, start_date=self.get_future_date(0),
        )
        self.client.force_authenticate(self.other_member)
        r = self.client.get('/api/workouts/assignments/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 0)

    def test_member_only_sees_templates_they_are_assigned_to(self):
        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/templates/')
        self.assertEqual(r.data['count'], 0)  # not assigned yet

        WorkoutAssignment.objects.create(
            template=self.approved_template, member=self.member,
            status=WorkoutAssignment.Status.ACTIVE, start_date=self.get_future_date(0),
        )
        r = self.client.get('/api/workouts/templates/')
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['id'], self.approved_template.id)
# ... rest of file (kept same)



class WorkoutTemplateDuplicateTestCase(APITestCase):
    def setUp(self):
        self.trainer = make_user('trainer4@gym.com', role=User.Role.TRAINER)
        self.template = WorkoutTemplate.objects.create(
            name='Original', trainer=self.trainer, duration_weeks=4,
            status=WorkoutTemplate.Status.APPROVED,
        )
        self.day = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=1)

    def test_duplicate_creates_independent_draft_copy(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/duplicate/')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        clone_id = r.data['id']

        clone = WorkoutTemplate.objects.get(id=clone_id)
        self.assertNotEqual(clone.id, self.template.id)
        self.assertEqual(clone.status, WorkoutTemplate.Status.DRAFT)
        self.assertEqual(clone.days.count(), 1)

        # Editing the clone's day must not touch the original's.
        clone_day = clone.days.first()
        clone_day.day_name = 'Changed'
        clone_day.save()
        self.day.refresh_from_db()
        self.assertNotEqual(self.day.day_name, 'Changed')


class WorkoutDayMoveTestCase(APITestCase):
    def setUp(self):
        self.trainer = make_user('trainer5@gym.com', role=User.Role.TRAINER)
        self.template = WorkoutTemplate.objects.create(
            name='Move Test', trainer=self.trainer, duration_weeks=4,
        )
        self.day1 = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=1, day_name='First')
        self.day2 = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=2, day_name='Second')
        self.day3 = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=3, day_name='Third')

    def test_move_down_swaps_with_next_day(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/days/{self.day1.id}/move/', {'direction': 'down'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.day1.refresh_from_db()
        self.day2.refresh_from_db()
        self.assertEqual(self.day1.day_number, 2)
        self.assertEqual(self.day2.day_number, 1)
        # Nothing lost, nothing duplicated — still exactly 3 days on distinct numbers.
        numbers = sorted(WorkoutDay.objects.filter(template=self.template).values_list('day_number', flat=True))
        self.assertEqual(numbers, [1, 2, 3])

    def test_cannot_move_first_day_up(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/days/{self.day1.id}/move/', {'direction': 'up'})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_move_last_day_down(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(f'/api/workouts/days/{self.day3.id}/move/', {'direction': 'down'})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class WorkoutTemplateVersionTestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner3@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer6@gym.com', role=User.Role.TRAINER)
        self.template = WorkoutTemplate.objects.create(
            name='Version Test', trainer=self.trainer, duration_weeks=4,
        )
        self.day = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=1, day_name='Original Day')

    def test_submit_and_approve_each_capture_a_version(self):
        self.client.force_authenticate(self.trainer)
        self.client.post(f'/api/workouts/templates/{self.template.id}/submit-review/')
        self.client.force_authenticate(self.owner)
        self.client.post(f'/api/workouts/templates/{self.template.id}/approve/')

        r = self.client.get(f'/api/workouts/templates/{self.template.id}/versions/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        reasons = [v['reason'] for v in r.data['results']] if 'results' in r.data else [v['reason'] for v in r.data]
        self.assertIn('submitted_for_review', reasons)
        self.assertIn('approved', reasons)

    def test_restore_reverts_a_later_edit(self):
        self.client.force_authenticate(self.trainer)
        self.client.post(f'/api/workouts/templates/{self.template.id}/submit-review/')  # captures v1 with 'Original Day'
        self.client.force_authenticate(self.owner)
        self.client.post(f'/api/workouts/templates/{self.template.id}/approve/')  # captures v2

        # Someone edits the day after approval.
        self.day.day_name = 'Edited Badly'
        self.day.save()

        version = self.template.versions.order_by('created_at').first()  # the submit-review snapshot
        r = self.client.post(f'/api/workouts/templates/{self.template.id}/versions/{version.id}/restore/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

        self.template.refresh_from_db()
        restored_day = self.template.days.first()
        self.assertEqual(restored_day.day_name, 'Original Day')


from apps.workouts.models import Exercise, WorkoutCompletionLog, WorkoutDayExercise


class ExerciseCRUDTestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner_ex@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer_ex@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member_ex@gym.com', role=User.Role.MEMBER)

    def test_trainer_can_create_exercise(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post('/api/workouts/exercises/', {
            'name': 'Bench Press', 'muscle_group': 'CHEST', 'exercise_type': 'STRENGTH',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_owner_can_create_exercise(self):
        self.client.force_authenticate(self.owner)
        r = self.client.post('/api/workouts/exercises/', {
            'name': 'Squat', 'muscle_group': 'LEGS', 'exercise_type': 'STRENGTH',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_create_exercise(self):
        self.client.force_authenticate(self.member)
        r = self.client.post('/api/workouts/exercises/', {
            'name': 'Deadlift', 'muscle_group': 'BACK', 'exercise_type': 'STRENGTH',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_list_exercises(self):
        r = self.client.get('/api/workouts/exercises/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_member_can_list_exercises(self):
        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/exercises/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_duplicate_exercise_name_rejected(self):
        self.client.force_authenticate(self.trainer)
        self.client.post('/api/workouts/exercises/', {
            'name': 'Push Up', 'muscle_group': 'CHEST', 'exercise_type': 'STRENGTH',
        })
        r = self.client.post('/api/workouts/exercises/', {
            'name': 'Push Up', 'muscle_group': 'CHEST', 'exercise_type': 'STRENGTH',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class CompletionLogTestCase(APITestCase):
    def setUp(self):
        self.trainer = make_user('trainer_cl@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member_cl@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('other_cl@gym.com', role=User.Role.MEMBER)
        self.template = WorkoutTemplate.objects.create(
            name='CL Test', trainer=self.trainer, status=WorkoutTemplate.Status.APPROVED,
        )
        self.day = WorkoutDay.objects.create(template=self.template, week_number=1, day_number=1)
        self.assignment = WorkoutAssignment.objects.create(
            template=self.template, member=self.member, start_date=date.today(),
        )

    def test_member_can_log_completion(self):
        self.client.force_authenticate(self.member)
        r = self.client.post('/api/workouts/completion-logs/', {
            'assignment': self.assignment.id,
            'workout_day': self.day.id,
            'date': str(date.today()),
            'status': 'COMPLETED',
            'duration_minutes': 45,
            'calories': 300,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_log_for_other_members_assignment(self):
        self.client.force_authenticate(self.other_member)
        r = self.client.post('/api/workouts/completion-logs/', {
            'assignment': self.assignment.id,
            'workout_day': self.day.id,
            'date': str(date.today()),
            'status': 'COMPLETED',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_list_own_logs(self):
        WorkoutCompletionLog.objects.create(
            assignment=self.assignment, workout_day=self.day,
            date=date.today(), status='COMPLETED',
        )
        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/completion-logs/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 1)


class AssignmentActionTestCase(APITestCase):
    def setUp(self):
        self.trainer = make_user('trainer_act@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member_act@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('other_act@gym.com', role=User.Role.MEMBER)
        self.template = WorkoutTemplate.objects.create(
            name='Action Test', trainer=self.trainer, status=WorkoutTemplate.Status.APPROVED,
        )
        self.assignment = WorkoutAssignment.objects.create(
            template=self.template, member=self.member, start_date=date.today(),
        )

    def test_member_can_pause_active_assignment(self):
        self.client.force_authenticate(self.member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/pause/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, WorkoutAssignment.Status.PAUSED)

    def test_member_can_resume_paused_assignment(self):
        self.assignment.status = WorkoutAssignment.Status.PAUSED
        self.assignment.save()
        self.client.force_authenticate(self.member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/resume/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, WorkoutAssignment.Status.ACTIVE)

    def test_member_can_cancel_assignment(self):
        self.client.force_authenticate(self.member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/cancel/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, WorkoutAssignment.Status.CANCELLED)

    def test_member_cannot_pause_other_members_assignment(self):
        self.client.force_authenticate(self.other_member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/pause/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_cannot_resume_active_assignment(self):
        self.client.force_authenticate(self.member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/resume/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_pause_already_paused(self):
        self.assignment.status = WorkoutAssignment.Status.PAUSED
        self.assignment.save()
        self.client.force_authenticate(self.member)
        r = self.client.post(f'/api/workouts/assignments/{self.assignment.id}/pause/')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class MessagingPermissionsTestCase(WorkoutAPITestCase):
    """Direct-message permission rules + recipient picker."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF, first_name='Sta', last_name='Ff')
        self.other_staff = make_user('staff2@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER, first_name='Tra', last_name='Iner')
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)
        self.template = WorkoutTemplate.objects.create(
            name='PPL', trainer=self.trainer, duration_weeks=4,
        )
        WorkoutAssignment.objects.create(
            template=self.template, member=self.member,
            assigned_by=self.trainer, start_date=self.get_future_date(-1),
        )

    def _send(self, user, recipient_id, message='hello'):
        self.client.force_authenticate(user)
        return self.client.post(
            '/api/workouts/messages/direct/',
            {'recipient_id': recipient_id, 'message': message},
            format='json',
        )

    def test_member_can_message_assigned_trainer(self):
        r = self._send(self.member, self.trainer.pk)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_can_message_staff(self):
        self.assertEqual(self._send(self.member, self.staff.pk).status_code, status.HTTP_201_CREATED)

    def test_member_cannot_initiate_conversation_with_owner(self):
        # No prior message from the owner -> member may not message them
        self.assertEqual(self._send(self.member, self.owner.pk).status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_continue_conversation_owner_started(self):
        # Owner messages the member first (TRAINER_REPLY, sender = owner)
        Notification.objects.create(
            recipient=self.member,
            notification_type=Notification.NotificationType.TRAINER_REPLY,
            title=f'Reply from {self.owner.get_full_name()}',
            message='Hi!',
            related_membership_id=self.owner.pk,
        )
        # Now the member can reply (continue) but not in reverse
        self.assertEqual(self._send(self.member, self.owner.pk).status_code, status.HTTP_201_CREATED)

    def test_member_cannot_message_other_members_or_other_trainers(self):
        self.assertEqual(self._send(self.member, self.other_member.pk).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._send(self.member, self.other_trainer.pk).status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_can_message_assigned_member_and_staff(self):
        self.assertEqual(self._send(self.trainer, self.member.pk).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._send(self.trainer, self.staff.pk).status_code, status.HTTP_201_CREATED)

    def test_trainer_cannot_message_unassigned_member_owner_or_other_trainer(self):
        self.assertEqual(self._send(self.trainer, self.other_member.pk).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._send(self.trainer, self.owner.pk).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._send(self.trainer, self.other_trainer.pk).status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_message_owner_member_trainer_and_other_staff(self):
        self.assertEqual(self._send(self.staff, self.owner.pk).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._send(self.staff, self.member.pk).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._send(self.staff, self.trainer.pk).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._send(self.staff, self.other_staff.pk).status_code, status.HTTP_201_CREATED)

    def test_owner_can_message_anyone(self):
        for u in (self.member, self.staff, self.trainer):
            self.assertEqual(self._send(self.owner, u.pk).status_code, status.HTTP_201_CREATED)

    def test_cannot_message_yourself(self):
        self.assertEqual(self._send(self.member, self.member.pk).status_code, status.HTTP_403_FORBIDDEN)

    def test_member_recipient_list_contains_trainer_and_staff_not_owner(self):
        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/message-recipients/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {u['user_id'] for u in r.data}
        self.assertIn(self.trainer.pk, ids)
        self.assertIn(self.staff.pk, ids)
        self.assertNotIn(self.owner.pk, ids)
        self.assertNotIn(self.other_member.pk, ids)

    def test_owner_never_in_member_recipients_picker_even_after_messaging(self):
        # Owner messaged the member -> member may reply (continue), but the
        # "New Message" picker still never offers the owner.
        Notification.objects.create(
            recipient=self.member,
            notification_type=Notification.NotificationType.TRAINER_REPLY,
            title=f'Reply from {self.owner.get_full_name()}',
            message='Hi!',
            related_membership_id=self.owner.pk,
        )
        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/message-recipients/')
        ids = {u['user_id'] for u in r.data}
        self.assertNotIn(self.owner.pk, ids)
        # ...but the member can still reply inside the existing conversation
        self.assertEqual(self._send(self.member, self.owner.pk).status_code, status.HTTP_201_CREATED)

    def test_staff_recipient_list_includes_owner(self):
        self.client.force_authenticate(self.staff)
        r = self.client.get('/api/workouts/message-recipients/')
        ids = {u['user_id'] for u in r.data}
        self.assertIn(self.owner.pk, ids)


class GroupMessagingTestCase(WorkoutAPITestCase):
    """Group chat creation, membership rules, send + read flows."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.member2 = make_user('member2@gym.com', role=User.Role.MEMBER)
        self.member3 = make_user('member3@gym.com', role=User.Role.MEMBER)
        self.template = WorkoutTemplate.objects.create(
            name='PPL', trainer=self.trainer, duration_weeks=4,
        )
        for m in (self.member, self.member2):
            WorkoutAssignment.objects.create(
                template=self.template, member=m,
                assigned_by=self.trainer, start_date=self.get_future_date(-1),
            )

    def _create_group(self, user, name='Team', member_ids=None):
        self.client.force_authenticate(user)
        return self.client.post(
            '/api/workouts/message-groups/',
            {'name': name, 'member_ids': member_ids or []},
            format='json',
        )

    def test_member_cannot_create_group(self):
        r = self._create_group(self.member, member_ids=[self.member2.pk])
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_can_create_group_with_assigned_members_only(self):
        r = self._create_group(self.trainer, member_ids=[self.member.pk, self.member2.pk])
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        # unassigned member rejected
        r = self._create_group(self.trainer, name='Bad', member_ids=[self.member3.pk])
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_create_group_but_not_with_owner(self):
        r = self._create_group(self.staff, member_ids=[self.member.pk, self.trainer.pk, self.member3.pk])
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        r = self._create_group(self.staff, name='WithOwner', member_ids=[self.owner.pk])
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create_group_with_anyone(self):
        r = self._create_group(self.owner, member_ids=[self.member.pk, self.staff.pk, self.trainer.pk, self.owner.pk])
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_send_and_list_messages_members_only(self):
        r = self._create_group(self.trainer, member_ids=[self.member.pk, self.member2.pk])
        group_id = r.data['id']

        # send as trainer
        self.client.force_authenticate(self.trainer)
        r = self.client.post(
            f'/api/workouts/message-groups/{group_id}/messages/',
            {'message': 'hello team'}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

        # member can list and sees it unread
        self.client.force_authenticate(self.member)
        r = self.client.get(f'/api/workouts/message-groups/{group_id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 1)
        self.assertFalse(r.data[0]['is_read'])

        # outsider cannot list
        self.client.force_authenticate(self.member3)
        r = self.client.get(f'/api/workouts/message-groups/{group_id}/')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_group_read_clears_unread_count(self):
        r = self._create_group(self.trainer, member_ids=[self.member.pk])
        group_id = r.data['id']
        self.client.force_authenticate(self.trainer)
        self.client.post(
            f'/api/workouts/message-groups/{group_id}/messages/',
            {'message': 'hi'}, format='json',
        )

        self.client.force_authenticate(self.member)
        r = self.client.get('/api/workouts/message-groups/')
        group = next(g for g in r.data if g['id'] == group_id)
        self.assertEqual(group['unread_count'], 1)

        self.client.post(f'/api/workouts/message-groups/{group_id}/read/')
        r = self.client.get('/api/workouts/message-groups/')
        group = next(g for g in r.data if g['id'] == group_id)
        self.assertEqual(group['unread_count'], 0)

    def test_sender_does_not_count_own_message_as_unread(self):
        r = self._create_group(self.trainer, member_ids=[self.member.pk])
        group_id = r.data['id']
        self.client.force_authenticate(self.trainer)
        self.client.post(
            f'/api/workouts/message-groups/{group_id}/messages/',
            {'message': 'hi'}, format='json',
        )
        r = self.client.get('/api/workouts/message-groups/')
        group = next(g for g in r.data if g['id'] == group_id)
        self.assertEqual(group['unread_count'], 0)  # trainer's own message not unread for them


class MessageEditDeletePinTestCase(WorkoutAPITestCase):
    """Edit / delete own messages and pin/unpin conversations."""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.template = WorkoutTemplate.objects.create(
            name='PPL', trainer=self.trainer, duration_weeks=4,
        )
        WorkoutAssignment.objects.create(
            template=self.template, member=self.member,
            assigned_by=self.trainer, start_date=self.get_future_date(-1),
        )

    def _member_to_staff_message(self):
        self.client.force_authenticate(self.member)
        r = self.client.post(
            '/api/workouts/messages/direct/',
            {'recipient_id': self.staff.pk, 'message': 'original text'},
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        return Notification.objects.filter(
            recipient=self.staff, related_membership_id=self.member.pk
        ).first()

    def test_sender_can_edit_own_direct_message(self):
        n = self._member_to_staff_message()
        self.client.force_authenticate(self.member)
        r = self.client.patch(
            f'/api/workouts/messages/direct/{n.pk}/',
            {'message': 'edited text'}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        n.refresh_from_db()
        self.assertEqual(n.message, 'edited text')
        self.assertTrue(n.is_edited)

    def test_recipient_cannot_edit_or_delete_senders_message(self):
        n = self._member_to_staff_message()
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.patch(f'/api/workouts/messages/direct/{n.pk}/', {'message': 'hacked'}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(f'/api/workouts/messages/direct/{n.pk}/').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertTrue(Notification.objects.filter(pk=n.pk).exists())

    def test_sender_can_delete_own_direct_message(self):
        n = self._member_to_staff_message()
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.delete(f'/api/workouts/messages/direct/{n.pk}/').status_code,
            status.HTTP_204_NO_CONTENT,
        )
        self.assertFalse(Notification.objects.filter(pk=n.pk).exists())

    def test_group_message_edit_delete_sender_only(self):
        self.client.force_authenticate(self.trainer)
        r = self.client.post(
            '/api/workouts/message-groups/',
            {'name': 'Team', 'member_ids': [self.member.pk]},
            format='json',
        )
        group_id = r.data['id']
        self.client.force_authenticate(self.trainer)
        r = self.client.post(
            f'/api/workouts/message-groups/{group_id}/messages/',
            {'message': 'hi team'}, format='json',
        )
        msg_id = r.data['id']

        # member (not sender) cannot edit/delete
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.patch(f'/api/workouts/message-groups/{group_id}/messages/{msg_id}/', {'message': 'x'}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        # sender can edit
        self.client.force_authenticate(self.trainer)
        r = self.client.patch(
            f'/api/workouts/message-groups/{group_id}/messages/{msg_id}/',
            {'message': 'updated'}, format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # sender can delete
        self.assertEqual(
            self.client.delete(f'/api/workouts/message-groups/{group_id}/messages/{msg_id}/').status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_pin_unpin_conversation(self):
        self.client.force_authenticate(self.member)
        # pin a direct conversation with staff
        r = self.client.post('/api/workouts/message-pins/', {'kind': 'direct', 'target_id': self.staff.pk}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        # pin a group (need to be a member) - create group as trainer then member joins? member added by trainer
        self.client.force_authenticate(self.trainer)
        r = self.client.post('/api/workouts/message-groups/', {'name': 'Team', 'member_ids': [self.member.pk]}, format='json')
        group_id = r.data['id']
        self.client.force_authenticate(self.member)
        r = self.client.post('/api/workouts/message-pins/', {'kind': 'group', 'target_id': group_id}, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

        r = self.client.get('/api/workouts/message-pins/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 2)

        # duplicate pin is idempotent
        self.client.post('/api/workouts/message-pins/', {'kind': 'direct', 'target_id': self.staff.pk}, format='json')
        r = self.client.get('/api/workouts/message-pins/')
        self.assertEqual(len(r.data), 2)

        # unpin
        self.assertEqual(
            self.client.delete(f"/api/workouts/message-pins/?kind=direct&target_id={self.staff.pk}").status_code,
            status.HTTP_204_NO_CONTENT,
        )
        r = self.client.get('/api/workouts/message-pins/')
        self.assertEqual(len(r.data), 1)

    def test_member_cannot_pin_group_they_are_not_in(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.post('/api/workouts/message-pins/', {'kind': 'group', 'target_id': 9999}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )


class UnauthenticatedWorkoutsTests(APITestCase):
    def test_unauthenticated_exercises_returns_401(self):
        r = self.client.get('/api/workouts/exercises/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_templates_returns_401(self):
        r = self.client.get('/api/workouts/templates/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_assignments_returns_401(self):
        r = self.client.get('/api/workouts/assignments/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)