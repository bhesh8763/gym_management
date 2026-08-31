"""
Tests for the Trainers app API — covers endpoints used by the trainer dashboard.

Run with:
    python manage.py test apps.trainers.tests

Coverage:
    - TrainerMemberAssignment CRUD (Owner/Staff/Trainer access)
    - MyAssignedMembersView (/api/trainers/my-members/)
    - Trainer can only see their own assigned members
    - Trainer cannot create/delete assignments (Owner/Staff only)
    - Members and unauthenticated users are denied
    - Workout templates visibility for trainers
    - Diet plan visibility for trainers
    - Attendance records visibility for trainers
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.trainers.models import TrainerMemberAssignment, TrainerProfile

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


def auth_headers(user):
    token = RefreshToken.for_user(user)
    return {'HTTP_AUTHORIZATION': f'Bearer {str(token.access_token)}'}


# ─── MyAssignedMembersView ───────────────────────────────────────────────────

class MyAssignedMembersTestCase(APITestCase):
    """
    GET /api/trainers/my-members/
    Trainer-only endpoint used by the trainer dashboard.
    """

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                 first_name='Coach', last_name='Smith')
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER,
                                       first_name='Coach', last_name='Jones')
        self.member1 = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')
        self.member2 = make_user('bob@gym.com', role=User.Role.MEMBER,
                                 first_name='Bob', last_name='Jones')
        self.member3 = make_user('carol@gym.com', role=User.Role.MEMBER,
                                 first_name='Carol', last_name='White')
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)

        # Assign members to trainer
        self.assignment1 = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member1, is_active=True,
        )
        self.assignment2 = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member2, is_active=True,
        )
        # Inactive assignment — should not show up
        self.inactive_assignment = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member3, is_active=False,
        )
        # Member assigned to a different trainer
        self.other_assignment = TrainerMemberAssignment.objects.create(
            trainer=self.other_trainer, member=self.member3, is_active=True,
        )

    def test_trainer_can_access_my_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 2)

    def test_trainer_only_sees_own_active_assignments(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        member_ids = [m['member_id'] for m in r.data]
        self.assertIn(self.member1.id, member_ids)
        self.assertIn(self.member2.id, member_ids)
        # member3 has an inactive assignment with this trainer — should not appear
        self.assertNotIn(self.member3.id, member_ids)

    def test_my_members_response_structure(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        member = r.data[0]
        self.assertIn('id', member)
        self.assertIn('member_id', member)
        self.assertIn('member_name', member)
        self.assertIn('member_email', member)
        self.assertIn('member_phone', member)
        self.assertIn('member_display_id', member)
        self.assertIn('assigned_date', member)
        self.assertIn('notes', member)

    def test_other_trainer_sees_only_own_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.other_trainer).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['member_id'], self.member3.id)

    def test_member_cannot_access_my_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.member1).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_cannot_access_my_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_access_my_members(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.staff).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_denied(self):
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_trainer_with_no_members_returns_empty(self):
        lonely_trainer = make_user('lonely@gym.com', role=User.Role.TRAINER)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(lonely_trainer).access_token}')
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 0)


# ─── TrainerMemberAssignment CRUD ─────────────────────────────────────────────

class TrainerAssignmentListTestCase(APITestCase):
    """
    GET /api/trainers/assignments/
    Owner/Staff see all; Trainer sees only own; Member sees nothing.
    """

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.member2 = make_user('member2@gym.com', role=User.Role.MEMBER)

        self.assignment1 = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member, is_active=True,
        )
        self.assignment2 = TrainerMemberAssignment.objects.create(
            trainer=self.other_trainer, member=self.member2, is_active=True,
        )

    def test_owner_can_list_all_assignments(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_staff_can_list_all_assignments(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.staff).access_token}')
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_trainer_sees_only_own_assignments(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['trainer'], self.trainer.id)

    def test_member_cannot_list_assignments(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.member).access_token}')
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_assignments_contain_trainer_and_member_ids(self):
        """Each assignment should include trainer and member foreign key ids."""
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        for a in results:
            self.assertIn('trainer', a)
            self.assertIn('member', a)
            self.assertIn('is_active', a)


class TrainerAssignmentCreateTestCase(APITestCase):
    """
    POST /api/trainers/assignments/
    Only Owner/Staff can create assignments.
    """

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_owner_can_create_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.post('/api/trainers/assignments/', {
            'trainer': self.trainer.id,
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TrainerMemberAssignment.objects.count(), 1)

    def test_staff_can_create_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.staff).access_token}')
        r = self.client.post('/api/trainers/assignments/', {
            'trainer': self.trainer.id,
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_trainer_cannot_create_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.post('/api/trainers/assignments/', {
            'trainer': self.trainer.id,
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_create_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.member).access_token}')
        r = self.client.post('/api/trainers/assignments/', {
            'trainer': self.trainer.id,
            'member': self.member.id,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class TrainerAssignmentUpdateTestCase(APITestCase):
    """
    PATCH /api/trainers/assignments/<id>/
    Owner/Staff can update; Trainer cannot.
    """

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.assignment = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member, is_active=True,
        )

    def test_owner_can_update_assignment_notes(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.patch(f'/api/trainers/assignments/{self.assignment.id}/', {
            'notes': 'Updated by owner',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.notes, 'Updated by owner')

    def test_trainer_cannot_update_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.patch(f'/api/trainers/assignments/{self.assignment.id}/', {
            'is_active': False,
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class TrainerAssignmentDeleteTestCase(APITestCase):
    """
    DELETE /api/trainers/assignments/<id>/
    Only Owner can delete (soft-deactivate).
    """

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.assignment = TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member, is_active=True,
        )

    def test_owner_can_delete_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        r = self.client.delete(f'/api/trainers/assignments/{self.assignment.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.is_active)

    def test_staff_cannot_delete_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.staff).access_token}')
        r = self.client.delete(f'/api/trainers/assignments/{self.assignment.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_cannot_delete_assignment(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.delete(f'/api/trainers/assignments/{self.assignment.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


# ─── Trainer can access shared endpoints used by dashboard ────────────────────

class TrainerAccessToWorkoutTemplatesTestCase(APITestCase):
    """
    Trainers should be able to list workout templates (filtered to their own
    + approved ones). This is used by the trainer dashboard stat card.
    """

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

        from apps.workouts.models import WorkoutTemplate
        self.own_template = WorkoutTemplate.objects.create(
            name='My Plan', trainer=self.trainer, status='APPROVED', duration_weeks=4,
        )
        self.other_template = WorkoutTemplate.objects.create(
            name='Other Plan', trainer=self.other_trainer, status='APPROVED', duration_weeks=4,
        )
        self.draft_template = WorkoutTemplate.objects.create(
            name='Draft Plan', trainer=self.trainer, status='DRAFT', duration_weeks=4,
        )

    def test_trainer_can_list_own_workout_templates(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/workouts/templates/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        template_ids = [t['id'] for t in results]
        # Trainer sees their own templates
        self.assertIn(self.own_template.id, template_ids)
        self.assertIn(self.draft_template.id, template_ids)
        # Trainer does NOT see other trainer's templates
        self.assertNotIn(self.other_template.id, template_ids)

    def test_member_sees_no_templates_when_not_assigned(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.member).access_token}')
        r = self.client.get('/api/workouts/templates/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 0)


class TrainerAccessToAttendanceTestCase(APITestCase):
    """
    Trainers should be able to list attendance records.
    This is used by the trainer dashboard for today's attendance and chart.
    """

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

        from apps.attendance.models import Attendance
        self.attendance1 = Attendance.objects.create(
            user=self.member, attendance_type='MEMBER',
            date=date.today(), status='PRESENT',
        )
        self.attendance2 = Attendance.objects.create(
            user=self.other_member, attendance_type='MEMBER',
            date=date.today(), status='PRESENT',
        )

    def test_trainer_can_list_attendance(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/attendance/records/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        # Trainer can see all attendance records (for dashboard)
        self.assertGreaterEqual(len(results), 2)

    def test_trainer_can_filter_attendance_by_date(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        today = date.today().isoformat()
        r = self.client.get(f'/api/attendance/records/?date={today}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class TrainerAccessToDietPlansTestCase(APITestCase):
    """
    Trainers should be able to list diet plans they created.
    This is used by the trainer dashboard stat card.
    """

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.other_trainer = make_user('trainer2@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

        from apps.diet.models import DietPlan
        self.own_plan = DietPlan.objects.create(
            name='My Diet Plan', member=self.member,
            is_active=True, created_by=self.trainer,
        )
        self.other_plan = DietPlan.objects.create(
            name='Other Diet Plan', member=self.member,
            is_active=True, created_by=self.other_trainer,
        )

    def test_trainer_can_list_own_diet_plans(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/diet/diet-plans/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        plan_ids = [p['id'] for p in results]
        # Trainer sees plans they created
        self.assertIn(self.own_plan.id, plan_ids)
        # Trainer does NOT see other trainer's plans
        self.assertNotIn(self.other_plan.id, plan_ids)


class TrainerAccessToNotificationsTestCase(APITestCase):
    """
    Trainers should be able to see their notifications.
    This is used by the trainer dashboard topbar.
    """

    def setUp(self):
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        from apps.notifications.models import Notification
        self.notification = Notification.objects.create(
            recipient=self.trainer,
            notification_type='GENERAL',
            title='Test notification',
            message='You have a new assignment',
        )

    def test_trainer_can_list_notifications(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/notifications/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_trainer_can_filter_unread_notifications(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.get('/api/notifications/?is_read=false')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.notification.id)

    def test_trainer_can_mark_notification_as_read(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.trainer).access_token}')
        r = self.client.patch(f'/api/notifications/{self.notification.id}/read/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)


# ─── Unauthenticated access ──────────────────────────────────────────────────

class UnauthenticatedTrainerEndpointsTestCase(APITestCase):
    """All trainer-related endpoints require authentication."""

    def test_my_members_requires_auth(self):
        r = self.client.get('/api/trainers/my-members/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_assignments_requires_auth(self):
        r = self.client.get('/api/trainers/assignments/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profiles_requires_auth(self):
        r = self.client.get('/api/trainers/profiles/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
