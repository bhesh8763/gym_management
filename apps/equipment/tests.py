"""
Tests for the Equipment app API.

Run with:
    python manage.py test apps.equipment.tests

Coverage:
    - Equipment create (POST /api/equipment/equipment/)
    - Maintenance record create (POST /api/equipment/maintenance/)
    - recorded_by auto-populated from the authenticated user
    - Filtering equipment by category/condition
    - Filtering maintenance by equipment/status
    - RBAC: members cannot manage equipment or maintenance
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.equipment.models import Equipment, MaintenanceRecord

User = get_user_model()


def make_user(email, role=User.Role.MEMBER, first_name='Test', last_name='User',
              password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name=first_name, last_name=last_name,
        role=role, **kwargs
    )


class EquipmentAPITestCase(APITestCase):
    def setUp(self):
        self.owner = make_user('owner@gym.com', role=User.Role.OWNER,
                                first_name='Owner', last_name='User')
        self.staff = make_user('staff@gym.com', role=User.Role.STAFF,
                                first_name='Staff', last_name='User')
        self.member = make_user('alice@gym.com', role=User.Role.MEMBER,
                                 first_name='Alice', last_name='Smith')
        self.equipment_url = '/api/equipment/equipment/'
        self.maintenance_url = '/api/equipment/maintenance/'

    def auth_as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(user).access_token)}'
        )


class EquipmentCreateTests(EquipmentAPITestCase):
    def test_staff_can_create_equipment(self):
        self.auth_as(self.staff)
        r = self.client.post(self.equipment_url, {
            'name': 'Treadmill',
            'category': 'Cardio',
            'brand': 'Hirox',
            'quantity': 3,
            'location': 'Ground Floor',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['condition'], 'GOOD')  # default

    def test_member_cannot_create_equipment(self):
        self.auth_as(self.member)
        r = self.client.post(self.equipment_url, {
            'name': 'Treadmill',
            'category': 'Cardio',
            'quantity': 1,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)


class EquipmentFilterTests(EquipmentAPITestCase):
    def setUp(self):
        super().setUp()
        Equipment.objects.create(name='Treadmill', category='Cardio', quantity=3)
        Equipment.objects.create(
            name='Bench Press', category='Strength', quantity=2,
            condition=Equipment.Condition.FAIR,
        )

    def test_filter_by_category(self):
        self.auth_as(self.owner)
        r = self.client.get(self.equipment_url, {'category': 'Strength'})
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['name'], 'Bench Press')

    def test_filter_by_condition(self):
        self.auth_as(self.owner)
        r = self.client.get(self.equipment_url, {'condition': 'FAIR'})
        self.assertEqual(r.data['count'], 1)


class MaintenanceRecordTests(EquipmentAPITestCase):
    def setUp(self):
        super().setUp()
        self.treadmill = Equipment.objects.create(
            name='Treadmill', category='Cardio', quantity=1,
        )

    def test_staff_can_log_maintenance(self):
        self.auth_as(self.staff)
        r = self.client.post(self.maintenance_url, {
            'equipment': self.treadmill.id,
            'maintenance_type': 'ROUTINE',
            'scheduled_date': '2026-07-25',
            'cost': '1200.00',
            'description': 'Belt check',
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data['recorded_by'], self.staff.id)
        self.assertEqual(r.data['status'], 'SCHEDULED')  # default

    def test_member_cannot_log_maintenance(self):
        self.auth_as(self.member)
        r = self.client.post(self.maintenance_url, {
            'equipment': self.treadmill.id,
            'maintenance_type': 'ROUTINE',
            'scheduled_date': '2026-07-25',
            'description': 'Belt check',
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_filter_by_equipment(self):
        MaintenanceRecord.objects.create(
            equipment=self.treadmill, maintenance_type='ROUTINE',
            scheduled_date='2026-07-25', description='Check',
        )
        other_equipment = Equipment.objects.create(name='Bike', category='Cardio', quantity=1)
        MaintenanceRecord.objects.create(
            equipment=other_equipment, maintenance_type='REPAIR',
            scheduled_date='2026-07-26', description='Fix pedal',
        )
        self.auth_as(self.owner)
        r = self.client.get(self.maintenance_url, {'equipment': self.treadmill.id})
        self.assertEqual(r.data['count'], 1)

    def test_filter_by_status(self):
        MaintenanceRecord.objects.create(
            equipment=self.treadmill, maintenance_type='ROUTINE',
            scheduled_date='2026-07-25', description='Check',
            status=MaintenanceRecord.MaintenanceStatus.COMPLETED,
        )
        self.auth_as(self.owner)
        r = self.client.get(self.maintenance_url, {'status': 'COMPLETED'})
        self.assertEqual(r.data['count'], 1)