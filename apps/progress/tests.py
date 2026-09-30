"""
Tests for the Progress app API.

Run with:
    python manage.py test apps.progress.tests

Coverage:
    - ProgressEntry CRUD (create, list, retrieve, update, delete)
    - ProgressEntry validation (date, weight, body fat, height, muscle mass)
    - PersonalRecord CRUD and validation
    - MemberStatsView (aggregated stats for member dashboard)
    - BMI calculation
    - Role-based access (Owner/Staff, Trainer, Member)
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.progress.models import ProgressEntry, PersonalRecord
from apps.trainers.models import TrainerMemberAssignment

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


def make_exercise(name='Bench Press'):
    from apps.workouts.models import Exercise
    return Exercise.objects.create(
        name=name, muscle_group='CHEST', exercise_type='STRENGTH',
    )


# ─── ProgressEntry CRUD ──────────────────────────────────────────────────────

class ProgressEntryCreateTestCase(APITestCase):
    """POST /api/progress/entries/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                first_name='Alice', last_name='Jones')
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

    def test_member_can_create_entry_for_self(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '75.50',
            'height_cm': '170.00',
            'body_fat_percentage': '18.50',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        entry = ProgressEntry.objects.first()
        self.assertEqual(entry.member, self.member)

    def test_trainer_can_create_entry_for_member(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '80.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        entry = ProgressEntry.objects.first()
        self.assertEqual(entry.member, self.member)
        self.assertEqual(entry.recorded_by, self.trainer)

    def test_owner_can_create_entry(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '65.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_create_entry_for_other_member(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.other_member.id,
            'date': date.today().isoformat(),
            'weight_kg': '70.00',
        }, format='json')
        # Member's own field is overridden by the serializer
        entry = ProgressEntry.objects.first()
        if entry:
            self.assertEqual(entry.member, self.member)


class ProgressEntryValidationTestCase(APITestCase):
    """Validation rules on ProgressEntry."""

    def setUp(self):
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)

    def test_future_date_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        future = date.today() + timedelta(days=1)
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': future.isoformat(),
            'weight_kg': '70.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weight_too_low_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '10.00',  # below 20
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weight_too_high_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '350.00',  # above 300
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_body_fat_too_high_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'body_fat_percentage': '65.00',  # above 60
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_height_out_of_range_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'height_cm': '400.00',  # above 300
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_muscle_mass_out_of_range_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'muscle_mass_kg': '200.00',  # above 150
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_entry_accepted(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '75.00',
            'height_cm': '175.00',
            'body_fat_percentage': '18.00',
            'muscle_mass_kg': '35.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_duplicate_date_rejected(self):
        ProgressEntry.objects.create(
            member=self.member, date=date.today(),
            weight_kg=Decimal('75.00'),
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/entries/', {
            'member': self.member.id,
            'date': date.today().isoformat(),
            'weight_kg': '76.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class ProgressEntryListTestCase(APITestCase):
    """GET /api/progress/entries/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)

        self.entry1 = ProgressEntry.objects.create(
            member=self.member, date=date.today(),
            weight_kg=Decimal('75.00'), height_cm=Decimal('170.00'),
        )
        self.entry2 = ProgressEntry.objects.create(
            member=self.other_member, date=date.today(),
            weight_kg=Decimal('80.00'),
        )

        TrainerMemberAssignment.objects.create(
            trainer=self.trainer, member=self.member, is_active=True,
        )

    def test_member_sees_only_own_entries(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/entries/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.entry1.id)

    def test_owner_sees_all_entries(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/progress/entries/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_trainer_sees_assigned_member_entries(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.get('/api/progress/entries/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        entry_ids = [e['id'] for e in results]
        self.assertIn(self.entry1.id, entry_ids)
        self.assertNotIn(self.entry2.id, entry_ids)


class ProgressEntryRetrieveUpdateDeleteTestCase(APITestCase):
    """GET/PATCH/DELETE /api/progress/entries/<id>/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.entry = ProgressEntry.objects.create(
            member=self.member, date=date.today(),
            weight_kg=Decimal('75.00'), height_cm=Decimal('170.00'),
        )

    def test_member_can_retrieve_own_entry(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get(f'/api/progress/entries/{self.entry.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('bmi', r.data)

    def test_member_can_update_own_entry(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.patch(f'/api/progress/entries/{self.entry.id}/', {
            'weight_kg': '76.50',
            'notes': 'After 2 weeks of training',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.weight_kg, Decimal('76.50'))

    def test_member_can_delete_own_entry(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.delete(f'/api/progress/entries/{self.entry.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(ProgressEntry.objects.filter(id=self.entry.id).exists())


# ─── BMI Calculation ─────────────────────────────────────────────────────────

class BMICalculationTestCase(APITestCase):
    """Test the bmi property on ProgressEntry."""

    def test_bmi_calculated_correctly(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER)
        entry = ProgressEntry.objects.create(
            member=member, date=date.today(),
            weight_kg=Decimal('75.00'), height_cm=Decimal('175.00'),
        )
        # BMI = 75 / (1.75^2) = 75 / 3.0625 ≈ 24.49
        self.assertAlmostEqual(entry.bmi, 24.49, places=2)

    def test_bmi_none_without_height(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER)
        entry = ProgressEntry.objects.create(
            member=member, date=date.today(),
            weight_kg=Decimal('75.00'),
        )
        self.assertIsNone(entry.bmi)

    def test_bmi_none_without_weight(self):
        member = make_user('member@gym.com', role=User.Role.MEMBER)
        entry = ProgressEntry.objects.create(
            member=member, date=date.today(),
            height_cm=Decimal('175.00'),
        )
        self.assertIsNone(entry.bmi)


# ─── PersonalRecord CRUD ────────────────────────────────────────────────────

class PersonalRecordCreateTestCase(APITestCase):
    """POST /api/progress/personal-records/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.exercise = make_exercise('Bench Press')

    def test_member_can_create_pr_for_self(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/personal-records/', {
            'member': self.member.id,
            'exercise': self.exercise.id,
            'date': date.today().isoformat(),
            'value': '100.00',
            'unit': 'kg',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        pr = PersonalRecord.objects.first()
        self.assertEqual(pr.member, self.member)

    def test_trainer_can_create_pr_for_member(self):
        self.client.credentials(**auth_headers(self.trainer))
        r = self.client.post('/api/progress/personal-records/', {
            'member': self.member.id,
            'exercise': self.exercise.id,
            'date': date.today().isoformat(),
            'value': '120.00',
            'unit': 'kg',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_future_date_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/personal-records/', {
            'member': self.member.id,
            'exercise': self.exercise.id,
            'date': (date.today() + timedelta(days=1)).isoformat(),
            'value': '100.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_zero_value_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/personal-records/', {
            'member': self.member.id,
            'exercise': self.exercise.id,
            'date': date.today().isoformat(),
            'value': '0',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_value_rejected(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.post('/api/progress/personal-records/', {
            'member': self.member.id,
            'exercise': self.exercise.id,
            'date': date.today().isoformat(),
            'value': '-5.00',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class PersonalRecordListTestCase(APITestCase):
    """GET /api/progress/personal-records/"""

    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.other_member = make_user('member2@gym.com', role=User.Role.MEMBER)
        self.exercise = make_exercise('Deadlift')

        self.pr1 = PersonalRecord.objects.create(
            member=self.member, exercise=self.exercise,
            date=date.today(), value=Decimal('150.00'), unit='kg',
        )
        self.pr2 = PersonalRecord.objects.create(
            member=self.other_member, exercise=self.exercise,
            date=date.today(), value=Decimal('200.00'), unit='kg',
        )

    def test_member_sees_only_own_prs(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/personal-records/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.pr1.id)

    def test_owner_sees_all_prs(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/progress/personal-records/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(len(results), 2)

    def test_pr_response_includes_exercise_name(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/personal-records/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        results = r.data.get('results', r.data)
        self.assertEqual(results[0]['exercise_name'], 'Deadlift')


# ─── MemberStatsView ─────────────────────────────────────────────────────────

class MemberStatsViewTestCase(APITestCase):
    """GET /api/progress/member-stats/"""

    def setUp(self):
        self.member = make_user('member@gym.com', role=User.Role.MEMBER)
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER)
        self.exercise = make_exercise('Squat')

    def test_member_can_access_stats(self):
        ProgressEntry.objects.create(
            member=self.member, date=date.today() - timedelta(days=30),
            weight_kg=Decimal('80.00'), height_cm=Decimal('175.00'),
        )
        ProgressEntry.objects.create(
            member=self.member, date=date.today(),
            weight_kg=Decimal('78.00'), height_cm=Decimal('175.00'),
            body_fat_percentage=Decimal('18.00'),
        )
        PersonalRecord.objects.create(
            member=self.member, exercise=self.exercise,
            date=date.today() - timedelta(days=30),
            value=Decimal('100.00'), unit='kg',
        )
        PersonalRecord.objects.create(
            member=self.member, exercise=self.exercise,
            date=date.today(),
            value=Decimal('120.00'), unit='kg',
        )

        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/member-stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['total_entries'], 2)
        self.assertIsNotNone(r.data['first_entry'])
        self.assertIsNotNone(r.data['latest_entry'])
        self.assertEqual(r.data['first_entry']['weight_kg'], 80.0)
        self.assertEqual(r.data['latest_entry']['weight_kg'], 78.0)
        self.assertIn('attendance', r.data)
        self.assertIn('personal_records', r.data)

    def test_non_member_forbidden(self):
        self.client.credentials(**auth_headers(self.owner))
        r = self.client.get('/api/progress/member-stats/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_stats_with_no_entries(self):
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/member-stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['total_entries'], 0)
        self.assertIsNone(r.data['first_entry'])
        self.assertIsNone(r.data['latest_entry'])
        self.assertEqual(r.data['all_entries'], [])

    def test_stats_includes_pr_summary(self):
        PersonalRecord.objects.create(
            member=self.member, exercise=self.exercise,
            date=date.today() - timedelta(days=60),
            value=Decimal('80.00'), unit='kg',
        )
        PersonalRecord.objects.create(
            member=self.member, exercise=self.exercise,
            date=date.today(),
            value=Decimal('100.00'), unit='kg',
        )
        self.client.credentials(**auth_headers(self.member))
        r = self.client.get('/api/progress/member-stats/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        pr_summary = r.data['personal_records']
        self.assertEqual(len(pr_summary), 1)
        self.assertEqual(pr_summary[0]['exercise'], 'Squat')
        self.assertEqual(pr_summary[0]['first']['value'], 80.0)
        self.assertEqual(pr_summary[0]['latest']['value'], 100.0)
