"""
Tests for the Staff app API.

Run with:
    python manage.py test apps.staff.tests

Coverage:
    - Staff profile create (POST /api/staff/profiles/)
    - One profile per user (OneToOneField) is enforced
    - Leave request create (POST /api/staff/leave-requests/)
    - requester is auto-set to the authenticated user, not client-supplied
    - Non-owner/staff only see their own leave requests
    - Review action (approve/reject) restricted to owner/staff
    - Shift template CRUD permissions (POST /api/staff/shifts/)
    - Default shift templates seeded by data migration
    - StaffShift overlap rejection on the same weekday
    - Schedules list/create/delete permissions and ?staff/?weekday/?shift filters
    - Bulk-set replaces a weekly schedule atomically, rejecting overlaps
    - Roster groups the week weekday -> shift -> staff
    - shifts_summary computed on the staff serializer
"""
from datetime import time, timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.staff.models import StaffProfile, LeaveRequest, Shift, StaffShift

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class StaffAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.trainer = make_user('trainer@gym.com', role=User.Role.TRAINER,
                                  first_name='Trainer', last_name='User')
        self.member = make_user('member@gym.com', role=User.Role.MEMBER,
                                 first_name='Member', last_name='User')
        self.profiles_url = '/api/staff/profiles/'
        self.leaves_url = '/api/staff/leave-requests/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )
    
    def get_future_dates(self):
        start = timezone.now().date() + timedelta(days=1)
        end = start + timedelta(days=2)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


class StaffProfileTests(StaffAPITestCase):
    def test_owner_can_create_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'user': self.trainer.id,
            'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_duplicate_profile_for_same_user_is_rejected(self):
        self.auth_as(self.owner)
        payload = {
            'user': self.trainer.id,
            'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
            'salary': '25000.00',
        }
        first = self.client.post(self.profiles_url, payload)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.profiles_url, payload)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_create_profile(self):
        self.auth_as(self.member)
        r = self.client.post(self.profiles_url, {
            'user': self.member.id, 'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_staff_or_trainer_role_can_have_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'user': self.member.id, 'role': 'RECEPTIONIST',
            'joined_date': '2026-01-01',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffCreateSerializerTests(StaffAPITestCase):
    def test_owner_can_create_staff_user_and_profile(self):
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'email': 'newstaff@gym.com', 'first_name': 'New', 'last_name': 'Staff',
            'password': 'StrongPass123!', 'role': 'GYM_KEEPER',
            'joined_date': '2026-06-01',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newstaff@gym.com')
        self.assertEqual(user.role, User.Role.STAFF)
        self.assertTrue(user.check_password('StrongPass123!'))
        self.assertTrue(StaffProfile.objects.filter(user=user).exists())

    def test_duplicate_email_rejected(self):
        self.auth_as(self.owner)
        payload = {'email': 'dup@gym.com', 'first_name': 'Dup', 'last_name': 'User', 'password': 'StrongPass123!'}
        self.client.post(self.profiles_url, payload)
        r = self.client.post(self.profiles_url, payload)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffProfileActionTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as(self.owner)
        r = self.client.post(self.profiles_url, {
            'email': 'actionstaff@gym.com', 'first_name': 'Action',
            'last_name': 'Staff', 'password': 'StrongPass123!', 'role': 'RECEPTIONIST',
        })
        self.profile_id = r.data['id']

    def test_owner_can_deactivate_staff(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertFalse(user.is_active)

    def test_owner_can_activate_staff(self):
        self.auth_as(self.owner)
        self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/activate/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertTrue(user.is_active)

    def test_owner_can_reset_password(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/reset-password/', {
            'new_password': 'NewStrongPass456!',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        user = User.objects.get(email='actionstaff@gym.com')
        self.assertTrue(user.check_password('NewStrongPass456!'))

    def test_reset_password_requires_new_password(self):
        self.auth_as(self.owner)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/reset-password/', {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_deactivate_staff(self):
        self.auth_as(self.member)
        r = self.client.post(f'{self.profiles_url}{self.profile_id}/deactivate/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class StaffAuthTests(APITestCase):
    def test_unauthenticated_profiles_returns_401(self):
        r = self.client.get('/api/staff/profiles/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unauthenticated_leaves_returns_401(self):
        r = self.client.get('/api/staff/leave-requests/')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class LeaveRequestTests(StaffAPITestCase):
    def test_trainer_can_submit_own_leave_request(self):
        self.auth_as(self.trainer)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK',
            'start_date': start,
            'end_date': end,
            'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['requester'], self.trainer.id)
        self.assertEqual(r.data['status'], 'PENDING')

    def test_requester_field_cannot_be_spoofed(self):
        self.auth_as(self.trainer)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'requester': self.owner.id,
            'leave_type': 'SICK',
            'start_date': start,
            'end_date': end,
            'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['requester'], self.trainer.id)

    def test_member_cannot_submit_leave_request(self):
        self.auth_as(self.member)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK', 'start_date': start, 'end_date': end, 'reason': 'Fever',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_submit_own_leave_request(self):
        self.auth_as(self.staff)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'CASUAL', 'start_date': start, 'end_date': end, 'reason': 'Personal',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_non_staff_only_sees_own_requests(self):
        LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        LeaveRequest.objects.create(
            requester=self.staff, leave_type='CASUAL',
            start_date='2026-07-22', end_date='2026-07-22', reason='Test',
        )
        self.auth_as(self.trainer)
        r = self.client.get(self.leaves_url)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['requester'], self.trainer.id)

    def test_owner_sees_all_requests(self):
        LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        LeaveRequest.objects.create(
            requester=self.staff, leave_type='CASUAL',
            start_date='2026-07-22', end_date='2026-07-22', reason='Test',
        )
        self.auth_as(self.owner)
        r = self.client.get(self.leaves_url)
        self.assertEqual(r.data['count'], 2)

    def test_owner_cannot_submit_leave_request(self):
        # Owners review leave requests; applying for leave is staff/trainer-only.
        self.auth_as(self.owner)
        start, end = self.get_future_dates()
        r = self.client.post(self.leaves_url, {
            'leave_type': 'CASUAL', 'start_date': start, 'end_date': end,
            'reason': 'Vacation',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(LeaveRequest.objects.count(), 0)

    def test_mine_param_returns_only_own_requests(self):
        LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        LeaveRequest.objects.create(
            requester=self.staff, leave_type='CASUAL',
            start_date='2026-07-22', end_date='2026-07-22', reason='Test',
        )
        # Staff's default list is trainers' requests (for review on
        # trainers.html); ?mine=1 gives back their own — "My Leave".
        self.auth_as(self.staff)
        r = self.client.get(self.leaves_url + '?mine=1')
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['requester'], self.staff.id)


class LeaveReviewTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.leave = LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date='2026-07-20', end_date='2026-07-21', reason='Test',
        )
        self.review_url = f'/api/staff/leave-requests/{self.leave.id}/review/'

    def test_owner_can_approve(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'APPROVED')
        self.assertEqual(r.data['reviewed_by'], self.owner.id)

    def test_trainer_cannot_approve_own_request(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_status_value_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {'status': 'MAYBE'})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_reject(self):
        self.auth_as(self.owner)
        r = self.client.post(self.review_url, {
            'status': 'REJECTED', 'review_note': 'Not enough notice',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['status'], 'REJECTED')
        self.assertEqual(r.data['review_note'], 'Not enough notice')

    def test_member_cannot_review(self):
        self.auth_as(self.member)
        r = self.client.post(self.review_url, {'status': 'APPROVED'})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class LeaveDateValidationTests(StaffAPITestCase):
    def test_end_date_before_start_date_rejected(self):
        self.auth_as(self.trainer)
        start = (timezone.now().date() + timedelta(days=5)).strftime('%Y-%m-%d')
        end = (timezone.now().date() + timedelta(days=1)).strftime('%Y-%m-%d')
        r = self.client.post(self.leaves_url, {
            'leave_type': 'SICK', 'start_date': start, 'end_date': end, 'reason': 'Wrong',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_overlapping_dates_rejected(self):
        self.auth_as(self.trainer)
        self.client.post(self.leaves_url, {
            'leave_type': 'SICK',
            'start_date': (timezone.now().date() + timedelta(days=10)).strftime('%Y-%m-%d'),
            'end_date': (timezone.now().date() + timedelta(days=12)).strftime('%Y-%m-%d'),
            'reason': 'First leave',
        })
        r = self.client.post(self.leaves_url, {
            'leave_type': 'CASUAL',
            'start_date': (timezone.now().date() + timedelta(days=11)).strftime('%Y-%m-%d'),
            'end_date': (timezone.now().date() + timedelta(days=13)).strftime('%Y-%m-%d'),
            'reason': 'Second leave',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class LeaveCancelTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        # Future dates: get_queryset() auto-rejects any PENDING leave whose
        # end_date has passed, which would 400 the cancel (date-rot: these
        # were future dates when the test was written).
        today = timezone.now().date()
        self.leave = LeaveRequest.objects.create(
            requester=self.trainer, leave_type='SICK',
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=12),
            reason='Test',
        )
        self.cancel_url = f'/api/staff/leave-requests/{self.leave.id}/cancel/'

    def test_requester_can_cancel_own_pending(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, 'CANCELLED')

    def test_cannot_cancel_other_users_leave(self):
        self.auth_as(self.staff)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_cancel_approved_leave(self):
        self.leave.status = 'APPROVED'
        self.leave.save(update_fields=['status'])
        self.auth_as(self.trainer)
        r = self.client.post(self.cancel_url)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class ShiftTemplateTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.shifts_url = '/api/staff/shifts/'
        self.admin = make_user('admin@gym.com', role=User.Role.ADMIN,
                               first_name='Admin', last_name='User')

    def test_default_templates_seeded(self):
        names = set(Shift.objects.values_list('name', flat=True))
        self.assertTrue({'Morning', 'Day', 'Evening', 'Night'} <= names)
        morning = Shift.objects.get(name='Morning')
        self.assertEqual(morning.start_time, time(5, 0))
        self.assertEqual(morning.end_time, time(10, 0))
        night = Shift.objects.get(name='Night')
        self.assertEqual(night.start_time, time(20, 0))
        self.assertEqual(night.end_time, time(22, 0))

    def test_owner_can_create_shift(self):
        self.auth_as(self.owner)
        r = self.client.post(self.shifts_url, {
            'name': 'Brunch', 'start_time': '10:00', 'end_time': '12:00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Shift.objects.filter(name='Brunch').exists())

    def test_admin_can_create_shift(self):
        self.auth_as(self.admin)
        r = self.client.post(self.shifts_url, {
            'name': 'Late Lunch', 'start_time': '13:00', 'end_time': '15:00',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_staff_can_read_shifts(self):
        self.auth_as(self.staff)
        r = self.client.get(self.shifts_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data['count'], 4)

    def test_staff_cannot_create_shift(self):
        self.auth_as(self.staff)
        r = self.client.post(self.shifts_url, {
            'name': 'Sneaky', 'start_time': '01:00', 'end_time': '02:00',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_trainer_cannot_create_shift(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.shifts_url, {
            'name': 'Sneaky', 'start_time': '01:00', 'end_time': '02:00',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_read_shifts(self):
        self.auth_as(self.member)
        r = self.client.get(self.shifts_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_shifts_returns_401(self):
        r = self.client.get(self.shifts_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_can_update_shift(self):
        shift = Shift.objects.get(name='Morning')
        self.auth_as(self.owner)
        r = self.client.patch(f'{self.shifts_url}{shift.id}/', {'name': 'Morning Peak'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        shift.refresh_from_db()
        self.assertEqual(shift.name, 'Morning Peak')

    def test_owner_can_delete_shift(self):
        shift = Shift.objects.create(
            name='Temp', start_time=time(23, 0), end_time=time(23, 30),
        )
        self.auth_as(self.owner)
        r = self.client.delete(f'{self.shifts_url}{shift.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Shift.objects.filter(pk=shift.id).exists())

    def test_end_before_start_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.shifts_url, {
            'name': 'Backwards', 'start_time': '14:00', 'end_time': '13:00',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_name_rejected(self):
        self.auth_as(self.owner)
        r = self.client.post(self.shifts_url, {
            'name': 'Morning', 'start_time': '05:00', 'end_time': '10:00',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class StaffShiftScheduleTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.schedules_url = '/api/staff/schedules/'
        self.morning, _ = Shift.objects.get_or_create(
            name='Morning', defaults={'start_time': time(5, 0), 'end_time': time(10, 0)},
        )
        self.day, _ = Shift.objects.get_or_create(
            name='Day', defaults={'start_time': time(10, 0), 'end_time': time(16, 0)},
        )
        # 08:00–14:00 overlaps Morning (05:00–10:00) and Day (10:00–16:00).
        self.overlap = Shift.objects.create(
            name='Overlap', start_time=time(8, 0), end_time=time(14, 0),
        )

    def assign(self, staff, shift, weekday):
        return self.client.post(self.schedules_url, {
            'staff': staff.id, 'shift': shift.id, 'weekday': weekday,
        })

    def test_owner_can_assign_shift(self):
        self.auth_as(self.owner)
        r = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['staff'], self.trainer.id)
        self.assertEqual(r.data['weekday_display'], 'Monday')

    def test_overlapping_shift_same_weekday_rejected(self):
        self.auth_as(self.owner)
        first = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.assign(self.trainer, self.overlap, 0)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            StaffShift.objects.filter(staff=self.trainer, weekday=0).count(), 1,
        )

    def test_back_to_back_shifts_allowed_same_day(self):
        self.auth_as(self.owner)
        first = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.assign(self.trainer, self.day, 0)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            StaffShift.objects.filter(staff=self.trainer, weekday=0).count(), 2,
        )

    def test_overlap_is_per_weekday_only(self):
        self.auth_as(self.owner)
        self.assertEqual(self.assign(self.trainer, self.morning, 0).status_code, 201)
        r = self.assign(self.trainer, self.overlap, 1)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_duplicate_shift_same_weekday_rejected(self):
        self.auth_as(self.owner)
        self.assertEqual(self.assign(self.trainer, self.morning, 0).status_code, 201)
        r = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_be_scheduled(self):
        self.auth_as(self.owner)
        r = self.assign(self.member, self.morning, 0)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(StaffShift.objects.filter(staff=self.member).exists())

    def test_trainer_cannot_create_schedule(self):
        self.auth_as(self.trainer)
        r = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_role_cannot_create_schedule(self):
        self.auth_as(self.staff)
        r = self.assign(self.trainer, self.morning, 0)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_cannot_list_schedules(self):
        self.auth_as(self.member)
        r = self.client.get(self.schedules_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_sees_only_own_schedules(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.trainer, shift=self.day, weekday=1)
        StaffShift.objects.create(staff=self.staff, shift=self.morning, weekday=2)
        self.auth_as(self.staff)
        r = self.client.get(self.schedules_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['staff'], self.staff.id)

    def test_owner_sees_all_schedules(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.staff, shift=self.morning, weekday=1)
        self.auth_as(self.owner)
        r = self.client.get(self.schedules_url)
        self.assertEqual(r.data['count'], 2)

    def test_staff_weekday_shift_filters(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.trainer, shift=self.day, weekday=1)
        StaffShift.objects.create(staff=self.staff, shift=self.morning, weekday=2)
        self.auth_as(self.owner)
        self.assertEqual(
            self.client.get(f'{self.schedules_url}?staff={self.trainer.id}').data['count'], 2,
        )
        self.assertEqual(
            self.client.get(f'{self.schedules_url}?weekday=0').data['count'], 1,
        )
        self.assertEqual(
            self.client.get(f'{self.schedules_url}?shift={self.morning.id}').data['count'], 2,
        )
        r = self.client.get(f'{self.schedules_url}?weekday=abc')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_delete_schedule(self):
        row = StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        self.auth_as(self.owner)
        r = self.client.delete(f'{self.schedules_url}{row.id}/')
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(StaffShift.objects.filter(pk=row.id).exists())

    def test_trainer_cannot_delete_schedule(self):
        row = StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        self.auth_as(self.trainer)
        r = self.client.delete(f'{self.schedules_url}{row.id}/')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(StaffShift.objects.filter(pk=row.id).exists())


class BulkSetTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.bulk_url = '/api/staff/schedules/bulk-set/'
        self.morning, _ = Shift.objects.get_or_create(
            name='Morning', defaults={'start_time': time(5, 0), 'end_time': time(10, 0)},
        )
        self.day, _ = Shift.objects.get_or_create(
            name='Day', defaults={'start_time': time(10, 0), 'end_time': time(16, 0)},
        )
        self.night, _ = Shift.objects.get_or_create(
            name='Night', defaults={'start_time': time(20, 0), 'end_time': time(22, 0)},
        )
        self.overlap = Shift.objects.create(
            name='Overlap', start_time=time(8, 0), end_time=time(14, 0),
        )

    def payload(self, staff=None, assignments=None):
        return {
            'staff': (staff or self.trainer).id,
            'assignments': assignments if assignments is not None else [],
        }

    def test_bulk_set_replaces_weekly_schedule(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[
            {'weekday': 0, 'shift_ids': [self.day.id]},
            {'weekday': 1, 'shift_ids': [self.morning.id, self.night.id]},
        ]), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 3)
        self.assertEqual(StaffShift.objects.filter(staff=self.trainer).count(), 3)
        self.assertFalse(
            StaffShift.objects.filter(
                staff=self.trainer, weekday=0, shift=self.morning,
            ).exists(),
        )
        self.assertTrue(
            StaffShift.objects.filter(
                staff=self.trainer, weekday=0, shift=self.day,
            ).exists(),
        )

    def test_bulk_set_rejects_overlapping_shifts_and_keeps_existing(self):
        existing = StaffShift.objects.create(
            staff=self.trainer, shift=self.morning, weekday=0,
        )
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[
            {'weekday': 0, 'shift_ids': [self.morning.id, self.overlap.id]},
        ]), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('overlap', str(r.data).lower())
        # Failed payload must not wipe the person's current schedule.
        self.assertEqual(
            list(StaffShift.objects.filter(staff=self.trainer).values_list(
                'id', flat=True,
            )),
            [existing.id],
        )

    def test_bulk_set_rejects_member(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(staff=self.member), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('STAFF or TRAINER', str(r.data))
        self.assertFalse(StaffShift.objects.filter(staff=self.member).exists())

    def test_bulk_set_rejects_invalid_weekday(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[
            {'weekday': 9, 'shift_ids': [self.morning.id]},
        ]), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_set_rejects_unknown_shift(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[
            {'weekday': 0, 'shift_ids': [999999]},
        ]), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_set_rejects_duplicate_weekday_entries(self):
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[
            {'weekday': 0, 'shift_ids': [self.morning.id]},
            {'weekday': 0, 'shift_ids': [self.day.id]},
        ]), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_set_with_empty_assignments_clears_schedule(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.trainer, shift=self.day, weekday=3)
        self.auth_as(self.owner)
        r = self.client.post(self.bulk_url, self.payload(assignments=[]), format='json')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['created'], 0)
        self.assertFalse(StaffShift.objects.filter(staff=self.trainer).exists())

    def test_trainer_cannot_bulk_set(self):
        self.auth_as(self.trainer)
        r = self.client.post(self.bulk_url, self.payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_role_cannot_bulk_set(self):
        self.auth_as(self.staff)
        r = self.client.post(self.bulk_url, self.payload(), format='json')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class RosterTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.roster_url = '/api/staff/schedules/roster/'
        self.morning, _ = Shift.objects.get_or_create(
            name='Morning', defaults={'start_time': time(5, 0), 'end_time': time(10, 0)},
        )
        self.night, _ = Shift.objects.get_or_create(
            name='Night', defaults={'start_time': time(20, 0), 'end_time': time(22, 0)},
        )

    def test_roster_groups_weekday_shift_staff(self):
        StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.staff, shift=self.morning, weekday=0)
        StaffShift.objects.create(staff=self.trainer, shift=self.night, weekday=1)
        self.auth_as(self.owner)
        r = self.client.get(self.roster_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        week = r.data['week']
        self.assertEqual(len(week), 7)
        monday = week[0]
        self.assertEqual(monday['weekday'], 0)
        self.assertEqual(monday['weekday_display'], 'Monday')
        self.assertEqual(len(monday['shifts']), 1)
        morning_slot = monday['shifts'][0]
        self.assertEqual(morning_slot['name'], 'Morning')
        self.assertEqual(
            {s['id'] for s in morning_slot['staff']},
            {self.trainer.id, self.staff.id},
        )
        tuesday = week[1]
        self.assertEqual(tuesday['shifts'][0]['name'], 'Night')
        self.assertEqual(tuesday['shifts'][0]['staff'][0]['id'], self.trainer.id)

    def test_roster_includes_empty_days(self):
        self.auth_as(self.owner)
        r = self.client.get(self.roster_url)
        self.assertEqual(len(r.data['week']), 7)
        self.assertTrue(all(day['shifts'] == [] for day in r.data['week']))

    def test_member_cannot_view_roster(self):
        self.auth_as(self.member)
        r = self.client.get(self.roster_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_roster_returns_401(self):
        r = self.client.get(self.roster_url)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class ShiftsSummaryTests(StaffAPITestCase):
    def setUp(self):
        super().setUp()
        self.profile = StaffProfile.objects.create(
            user=self.trainer, role=StaffProfile.Role.TRAINER,
        )
        self.profile_url = f'/api/staff/profiles/{self.profile.id}/'
        self.morning, _ = Shift.objects.get_or_create(
            name='Morning', defaults={'start_time': time(5, 0), 'end_time': time(10, 0)},
        )
        self.evening, _ = Shift.objects.get_or_create(
            name='Evening', defaults={'start_time': time(16, 0), 'end_time': time(20, 0)},
        )
        self.night, _ = Shift.objects.get_or_create(
            name='Night', defaults={'start_time': time(20, 0), 'end_time': time(22, 0)},
        )

    def test_summary_groups_consecutive_days(self):
        for weekday in range(5):
            StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=weekday)
            StaffShift.objects.create(staff=self.trainer, shift=self.night, weekday=weekday)
        self.auth_as(self.owner)
        r = self.client.get(self.profile_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['shifts_summary'], 'Mon-Fri: Morning, Night')

    def test_summary_joins_separate_groups(self):
        for weekday in range(5):
            StaffShift.objects.create(staff=self.trainer, shift=self.morning, weekday=weekday)
            StaffShift.objects.create(staff=self.trainer, shift=self.night, weekday=weekday)
        StaffShift.objects.create(staff=self.trainer, shift=self.evening, weekday=5)
        self.auth_as(self.owner)
        r = self.client.get(self.profile_url)
        self.assertEqual(
            r.data['shifts_summary'], 'Mon-Fri: Morning, Night; Sat: Evening',
        )

    def test_summary_none_without_shifts(self):
        self.auth_as(self.owner)
        r = self.client.get(self.profile_url)
        self.assertIsNone(r.data['shifts_summary'])