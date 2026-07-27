"""
Authentication and user profile views.

Endpoints:
    POST   /api/auth/register/          - Register a new user
    POST   /api/auth/login/             - Obtain JWT pair (login)
    POST   /api/auth/token/refresh/     - Refresh access token
    POST   /api/auth/logout/            - Blacklist refresh token (logout)
    GET    /api/auth/me/                - Get current user profile
    PATCH  /api/auth/me/                - Update current user profile
    POST   /api/auth/change-password/   - Change password
"""
from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import TokenError

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
