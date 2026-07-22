"""
Serializers for the Members app.

Handles member profile creation, update, and read with computed fields.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.members.models import MemberProfile

User = get_user_model()


# ─── Nested user serializer used inside profile responses ─────────────────────

class MemberUserSerializer(serializers.ModelSerializer):
    """Lightweight user fields embedded in profile responses."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'profile_picture', 'is_active', 'date_joined',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


# ─── Main profile serializers ─────────────────────────────────────────────────

class MemberProfileSerializer(serializers.ModelSerializer):
    """
    Full read serializer — returned by list, detail, and create/update responses.
    Includes nested user info and computed bmi.
    """
    user = MemberUserSerializer(read_only=True)
    bmi = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    fitness_goal_display = serializers.CharField(source='get_fitness_goal_display', read_only=True)
    fitness_level_display = serializers.CharField(source='get_fitness_level_display', read_only=True)

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'user',
            'date_of_birth', 'gender', 'gender_display',
            'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'height_cm', 'weight_kg', 'bmi',
            'fitness_goal', 'fitness_goal_display',
            'fitness_level', 'fitness_level_display',
            'medical_conditions', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']

    def get_bmi(self, obj):
        return obj.bmi


class MemberProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Write serializer for updating a member's own profile fields.
    Does not touch the linked User record — use MeView for that.
    """

    class Meta:
        model = MemberProfile
        fields = [
            'date_of_birth', 'gender', 'address',
            'emergency_contact_name', 'emergency_contact_phone',
            'height_cm', 'weight_kg',
            'fitness_goal', 'fitness_level',
            'medical_conditions', 'notes',
        ]


# ─── Member creation (admin/staff creates both user + profile) ────────────────

class MemberCreateSerializer(serializers.Serializer):
    """
    Used by Owner/Staff to create a new Member user + profile in one request.

    Required user fields:  email, first_name, last_name, password
    Optional user fields:  phone, profile_picture
    Optional profile fields: everything else
    """
    # User fields
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    profile_picture = serializers.ImageField(required=False, allow_null=True)
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    # Profile fields
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=MemberProfile.Gender.choices, required=False, allow_blank=True
    )
    address = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    emergency_contact_phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    height_cm = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )
    fitness_goal = serializers.ChoiceField(
        choices=MemberProfile.FitnessGoal.choices, required=False, allow_blank=True
    )
    fitness_level = serializers.ChoiceField(
        choices=MemberProfile.FitnessLevel.choices, required=False,
        default=MemberProfile.FitnessLevel.BEGINNER,
    )
    medical_conditions = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        # Split user vs profile fields
        user_fields = ['email', 'first_name', 'last_name', 'phone', 'profile_picture', 'password']
        user_data = {k: validated_data.pop(k) for k in user_fields if k in validated_data}
        password = user_data.pop('password')

        user = User(role=User.Role.MEMBER, **user_data)
        user.set_password(password)
        user.save()

        # Create or update the profile (signal may have auto-created it)
        profile, _ = MemberProfile.objects.get_or_create(user=user)
        for attr, value in validated_data.items():
            setattr(profile, attr, value)
        profile.save()

        return profile


# ─── List serializer (lighter, no nested user detail) ────────────────────────

class MemberListSerializer(serializers.ModelSerializer):
    """
    Compact serializer for the member list view.
    Shows key info without heavy nesting.
    """
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    is_active = serializers.BooleanField(source='user.is_active', read_only=True)
    profile_picture = serializers.ImageField(source='user.profile_picture', read_only=True)
    bmi = serializers.SerializerMethodField()
    fitness_goal_display = serializers.CharField(source='get_fitness_goal_display', read_only=True)
    fitness_level_display = serializers.CharField(source='get_fitness_level_display', read_only=True)

    class Meta:
        model = MemberProfile
        fields = [
            'id', 'user_id', 'full_name', 'email', 'phone', 'is_active',
            'profile_picture', 'gender',
            'fitness_goal', 'fitness_goal_display',
            'fitness_level', 'fitness_level_display',
            'bmi', 'created_at',
        ]

    def get_bmi(self, obj):
        return obj.bmi
