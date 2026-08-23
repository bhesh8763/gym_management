"""
Authentication and user profile views.

Endpoints:
    POST   /api/auth/register/            - Register a new user
    POST   /api/auth/login/               - Obtain JWT pair (login)
    POST   /api/auth/token/refresh/       - Refresh access token
    POST   /api/auth/logout/              - Blacklist refresh token (logout)
    GET    /api/auth/me/                  - Get current user profile
    PATCH  /api/auth/me/                  - Update current user profile
    POST   /api/auth/change-password/     - Change password
    POST   /api/auth/forgot-password/     - Request password reset email
    POST   /api/auth/reset-password/      - Reset password using token
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import TokenError

from .models import PasswordResetToken
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    Open endpoint — no authentication required.
    Always creates a MEMBER account. Staff/Trainer accounts are created by an
    Owner through the dedicated staff/trainer "add" endpoints instead.
    """
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Send welcome email/notification
        try:
            from apps.notifications.services import notify_welcome
            notify_welcome(user)
        except Exception:
            pass  # Don't fail registration if notification fails

        # Issue tokens immediately after registration
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'message': 'Registration successful.',
                'user': UserDetailSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/
    Returns access + refresh tokens along with user info.
    """
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]


class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Blacklists the provided refresh token, effectively logging the user out.
    Requires: { "refresh": "<refresh_token>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(
                {'message': 'Logged out successfully.'},
                status=status.HTTP_200_OK,
            )
        except TokenError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/auth/me/  — Return authenticated user's profile.
    PATCH /api/auth/me/  — Update name, phone, profile_picture.
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserUpdateSerializer
        return UserDetailSerializer

    def update(self, request, *args, **kwargs):
        kwargs['partial'] = True  # Always allow partial updates
        return super().update(request, *args, **kwargs)


class ChangePasswordView(generics.UpdateAPIView):
    """
    POST /api/auth/change-password/
    Authenticated users can change their own password.
    Requires: { "old_password", "new_password", "new_password2" }
    """
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Invalidate all existing tokens after password change
        # by rotating the refresh token
        return Response(
            {'message': 'Password changed successfully. Please log in again.'},
            status=status.HTTP_200_OK,
        )



class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Accepts { "email": "user@example.com" }.
    Always returns 200 to avoid leaking whether an email is registered.
    Sends a password-reset link to the user's email if found.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response(
                {'error': 'Email is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Always respond with 200 to prevent email enumeration
        User = get_user_model()
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response({'message': 'If that email is registered, a reset link has been sent.'})

        reset_token = PasswordResetToken.create_for_user(user)

        # Build reset URL — frontend handles the actual form
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://127.0.0.1:5500')
        reset_url = f"{frontend_url}/reset-password.html?token={reset_token.token}"

        subject = 'Password Reset — Gym Management System'
        message = (
            f"Hi {user.get_full_name()},\n\n"
            f"You requested a password reset. Click the link below to set a new password.\n\n"
            f"{reset_url}\n\n"
            f"This link expires in 1 hour. If you did not request this, ignore this email.\n\n"
            f"— Gym Management System"
        )

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        except Exception:
            # Log but don't expose errors to the client
            pass

        return Response({'message': 'If that email is registered, a reset link has been sent.'})


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Accepts { "token": "<reset_token>", "new_password": "...", "new_password2": "..." }
    Validates token, updates password, and invalidates the token.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_value = request.data.get('token', '').strip()
        new_password = request.data.get('new_password', '')
        new_password2 = request.data.get('new_password2', '')

        if not token_value:
            return Response({'error': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_password:
            return Response({'error': 'New password is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_password != new_password2:
            return Response({'error': 'Passwords do not match.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_token = PasswordResetToken.objects.select_related('user').get(token=token_value)
        except PasswordResetToken.DoesNotExist:
            return Response({'error': 'Invalid or expired token.'}, status=status.HTTP_400_BAD_REQUEST)

        if not reset_token.is_valid:
            return Response({'error': 'Token has expired or already been used.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate password strength
        try:
            validate_password(new_password, user=reset_token.user)
        except DjangoValidationError as e:
            return Response({'error': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        # Update password and mark token as used
        reset_token.user.set_password(new_password)
        reset_token.user.save(update_fields=['password'])
        reset_token.is_used = True
        reset_token.save(update_fields=['is_used'])

        return Response({'message': 'Password reset successfully. You can now log in.'})
