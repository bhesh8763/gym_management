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