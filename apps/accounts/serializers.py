"""
Serializers for authentication and user management.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends the default JWT pair serializer to embed user info into the token
    and return it in the response payload.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Custom claims embedded in JWT payload
        token['email'] = user.email
        token['full_name'] = user.get_full_name()
        token['role'] = user.role
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Append user info to the login response body
        data['user'] = UserDetailSerializer(self.user).data
        return data


class RegisterSerializer(serializers.ModelSerializer):
    """
    Handles new user (public, self-service) registration.
    Password is write-only and validated against Django password validators.

    Always creates a MEMBER — this endpoint is open (AllowAny), so it must
    never accept a caller-supplied role. Owner/Staff accounts are created
    through the dedicated Staff/Trainer "add" endpoints, which require an
    authenticated Owner/Staff request instead.
    """
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password2 = serializers.CharField(write_only=True, required=True, label='Confirm password')

    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name', 'phone',
            'password', 'password2',
        ]
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        password = validated_data.pop('password')
        user = User(role=User.Role.MEMBER, **validated_data)
        user.set_password(password)
        user.save()
        return user


class UserDetailSerializer(serializers.ModelSerializer):
    """
    Read-only serializer used for user profile responses and JWT payload.
    """
    full_name = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'display_id', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'role', 'profile_picture',
            'is_active', 'date_joined', 'last_login',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_profile_picture(self, obj):
        if not obj.profile_picture:
            return None
        request = self.context.get('request')
        url = obj.profile_picture.url
        if request:
            return request.build_absolute_uri(url)
        # Fallback: build absolute URI from settings
        from django.conf import settings
        base = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')
        return f"{base.rstrip('/')}{url}"


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Allows users to update their own profile (name, email, phone, picture).
    Role changes are not allowed here.
    """

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'profile_picture']


class ChangePasswordSerializer(serializers.Serializer):
    """Handles authenticated password change."""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True, write_only=True, validators=[validate_password]
    )
    new_password2 = serializers.CharField(required=True, write_only=True, label='Confirm new password')

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password2']:
            raise serializers.ValidationError({'new_password': 'Passwords do not match.'})
        return attrs

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Old password is incorrect.')
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user
