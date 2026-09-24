"""
Authentication and user profile views.

Endpoints:
    POST   /api/auth/register/            - Register a new user (creates OWNER)
    POST   /api/auth/subscribe/           - Record a simulated plan purchase
    GET    /api/auth/subscription/        - Current owner's plan status (gate)
    POST   /api/auth/login/               - Obtain JWT pair (login)
    POST   /api/auth/token/refresh/       - Refresh access token
    POST   /api/auth/logout/              - Blacklist refresh token (logout)
    GET    /api/auth/me/                  - Get current user profile
    PATCH  /api/auth/me/                  - Update current user profile
    POST   /api/auth/change-password/     - Change password
    POST   /api/auth/forgot-password/     - Request password reset email
    POST   /api/auth/reset-password/      - Reset password using token
"""
import logging
import uuid
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

from .models import PasswordResetToken, PlanSubscription
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    SubscribeSerializer,
    UserDetailSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()
logger = logging.getLogger('apps.accounts')


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    Open endpoint — no authentication required.
    Always creates an OWNER account (gym-owner onboarding flow: register →
    plan checkout on payment.html → dashboard). Members/Staff/Trainers are
    added later by the Owner through the dedicated "add" endpoints instead.
    """
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = 'auth'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

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


class SubscribeView(APIView):
    """
    POST /api/auth/subscribe/
    Records a simulated plan purchase from the signup checkout (payment.html).
    Requires an authenticated user (the freshly registered owner's JWT) and
    derives the price server-side — the client only picks plan + method.
    """
    permission_classes = [IsAuthenticated]

    PLAN_PRICES = {'starter': 4999, 'gold': 9999, 'platinum': 19999}

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data['plan']
        method = serializer.validated_data['method']

        while True:
            reference = 'TXN-' + uuid.uuid4().hex[:10].upper()
            if not PlanSubscription.objects.filter(reference=reference).exists():
                break

        sub = PlanSubscription.objects.create(
            user=request.user,
            plan=plan,
            price=self.PLAN_PRICES[plan],
            method=method,
            reference=reference,
            status='paid',
        )
        return Response(
            {
                'reference': sub.reference,
                'plan': sub.plan,
                'price': sub.price,
                'method': sub.method,
                'status': sub.status,
            },
            status=status.HTTP_201_CREATED,
        )


class SubscriptionView(APIView):
    """
    GET /api/auth/subscription/
    Returns the current user's latest plan purchase, or has_plan: false.
    Drives the frontend owner-plan gate: unpaid owners are redirected from
    any app page to payment.html until checkout completes.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sub = (
            PlanSubscription.objects.filter(user=request.user)
            .order_by('-created_at')
            .first()
        )
        if not sub:
            return Response({'has_plan': False})
        return Response({
            'has_plan': True,
            'plan': sub.plan,
            'price': sub.price,
            'method': sub.method,
            'reference': sub.reference,
            'created_at': sub.created_at.isoformat(),
        })


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/
    Returns access + refresh tokens along with user info.
    """
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = 'auth'


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
        user = serializer.save()

        # Invalidate every outstanding JWT for this user so that old access/
        # refresh tokens can't be used after the password changes.
        self._blacklist_user_tokens(user)

        return Response(
            {'message': 'Password changed successfully. Please log in again.'},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _blacklist_user_tokens(user):
        """Blacklist all outstanding tokens for `user` so existing sessions
        are terminated immediately after a password change or reset."""
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)



class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Accepts { "email": "user@example.com" }.
    Always returns 200 to avoid leaking whether an email is registered.
    Sends a password-reset link to the user's email if found.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response(
                {'error': 'Email is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Always respond with 200 to prevent email enumeration
        success_response = Response(
            {'message': 'If that email is registered, a reset link has been sent.'}
        )

        User = get_user_model()
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return success_response

        # Create token
        try:
            reset_token = PasswordResetToken.create_for_user(user)
        except Exception as e:
            logger.error('Failed to create reset token for %s: %s', email, e)
            return success_response

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
            logger.info('Password reset email sent to %s', user.email)
        except Exception as e:
            logger.error('Failed to send password reset email to %s: %s', user.email, e)

        return success_response


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Accepts { "token": "<reset_token>", "new_password": "...", "new_password2": "..." }
    Validates token, updates password, and invalidates the token.
    """
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = 'auth'

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

        # Invalidate all existing JWTs issued before the reset, so any
        # session that was active under the old password stops immediately.
        ChangePasswordView._blacklist_user_tokens(reset_token.user)

        return Response({'message': 'Password reset successfully. You can now log in.'})
