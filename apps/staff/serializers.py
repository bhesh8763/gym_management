from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from .models import StaffProfile, LeaveRequest

User = get_user_model()


class StaffProfileSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_display_id = serializers.CharField(source='user.display_id', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)

    class Meta:
        model = StaffProfile
        fields = [
            'id', 'user', 'user_name', 'user_email', 'user_display_id', 'is_active', 'department',
            'designation', 'joined_date', 'salary', 'id_document',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_user(self, value):
        if value.role != User.Role.STAFF:
            raise serializers.ValidationError(
                'Staff profiles can only be created for users with the STAFF role.'
            )
        return value


class StaffCreateSerializer(serializers.Serializer):
    """
    Used by Owner to create a new Staff user + profile in one request
    (mirrors apps.members.serializers.MemberCreateSerializer).

    Required user fields:  email, first_name, last_name, password
    Optional user fields:  phone
    Optional profile fields: department, designation, joined_date, salary, notes
    """
    # User fields
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    # Profile fields
    department = serializers.ChoiceField(
        choices=StaffProfile.Department.choices, required=False,
        default=StaffProfile.Department.FRONT_DESK,
    )
    designation = serializers.CharField(max_length=100, required=False, allow_blank=True)
    joined_date = serializers.DateField(required=False, allow_null=True)
    salary = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True, min_value=Decimal('0'),
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        user_fields = ['email', 'first_name', 'middle_name', 'last_name', 'phone', 'password']
        user_data = {k: validated_data.pop(k) for k in user_fields if k in validated_data}
        password = user_data.pop('password')

        user = User(role=User.Role.STAFF, **user_data)
        user.set_password(password)
        user.save()

        return StaffProfile.objects.create(user=user, **validated_data)


class LeaveRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.CharField(source='requester.get_full_name', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    duration_days = serializers.ReadOnlyField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'requester', 'requester_name', 'leave_type',
            'start_date', 'end_date', 'duration_days', 'reason', 'status',
            'reviewed_by', 'reviewed_by_name', 'review_note', 'created_at',
        ]
        read_only_fields = ['id', 'requester', 'status', 'reviewed_by', 'created_at']

    def validate_start_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError('Start date cannot be in the past.')
        return value

    def validate(self, data):
        start_date = data.get('start_date', getattr(self.instance, 'start_date', None))
        end_date = data.get('end_date', getattr(self.instance, 'end_date', None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {'end_date': 'End date cannot be before start date.'}
            )
        return data