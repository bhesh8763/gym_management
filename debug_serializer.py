from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from apps.staff.serializers import LeaveRequestSerializer
from django.contrib.auth import get_user_model
from rest_framework.request import Request
from django.test import RequestFactory

User = get_user_model()

class DebugTest(TestCase):
    def setUp(self):
        self.trainer = User.objects.create_user(
            email='trainer@gym.com', password='TestPass123!',
            role=User.Role.TRAINER, first_name='Trainer'
        )
        self.factory = RequestFactory()

    def test_serializer_validation_error(self):
        data = {
            'leave_type': 'SICK',
            'start_date': '2026-07-25',
            'end_date': '2026-07-26',
            'reason': 'Fever',
        }
        
        # Create a mock request
        request = self.factory.post('/api/staff/leave-requests/')
        request.user = self.trainer
        
        serializer = LeaveRequestSerializer(data=data, context={'request': Request(request)})
        if not serializer.is_valid():
            print(f"Validation errors: {serializer.errors}")
        else:
            print("Serializer is valid!")

if __name__ == '__main__':
    # We can't run this with `python manage.py test` directly from here
    # but we can run it as a standalone script if we set up django
    pass
