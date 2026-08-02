"""
Views for the Members app.

API Endpoints:
    GET    /api/members/                  - List all members (Owner/Staff/Trainer)
    POST   /api/members/                  - Create member + profile (Owner/Staff)
    GET    /api/members/<id>/             - Retrieve member profile (Owner/Staff/Trainer or self)
    PUT    /api/members/<id>/             - Full update profile (Owner/Staff)
    PATCH  /api/members/<id>/             - Partial update profile (Owner/Staff or self)
    DELETE /api/members/<id>/             - Deactivate member (Owner/Staff)
    POST   /api/members/<id>/reactivate/  - Reactivate member (Owner/Staff)
    GET    /api/members/me/               - Own profile (Member)
    PATCH  /api/members/me/              - Update own profile (Member)

Search/Filter (query params on list):
    ?search=<name|email|phone>
    ?fitness_goal=<WEIGHT_LOSS|MUSCLE_GAIN|…>
    ?fitness_level=<BEGINNER|INTERMEDIATE|ADVANCED>
    ?gender=<M|F|O|N>
    ?is_active=<true|false>
    ?ordering=<created_at|-created_at|full_name>
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import generics, status, filters
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrTrainer
from apps.members.models import MemberProfile
from apps.members.serializers import (
    MemberCreateSerializer,
    MemberListSerializer,
    MemberProfileSerializer,
    MemberProfileUpdateSerializer,
)

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_profile_or_404(pk):
    try:
        return MemberProfile.objects.select_related('user').get(pk=pk)
    except MemberProfile.DoesNotExist:
        raise NotFound(f'Member profile with id={pk} not found.')


# ─── Member List + Create ─────────────────────────────────────────────────────

class MemberListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/members/  — List members (Owner, Staff, Trainer)
    POST /api/members/  — Create member (Owner, Staff)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaff()]
        return [IsOwnerOrStaffOrTrainer()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MemberCreateSerializer
        return MemberListSerializer

    def get_queryset(self):
        from django.db.models import Prefetch
        from apps.memberships.models import Membership

        qs = MemberProfile.objects.select_related('user').filter(
            user__role=User.Role.MEMBER
        ).prefetch_related(
            Prefetch(
                'user__memberships',
                queryset=Membership.objects.exclude(status='CANCELLED').select_related('plan'),
                to_attr='_current_memberships',
            )
        )

        # ── Search ──────────────────────────────────────────────────────────
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__phone__icontains=search)
            )

        # ── Filters ──────────────────────────────────────────────────────────
        fitness_goal = self.request.query_params.get('fitness_goal')
        if fitness_goal:
            qs = qs.filter(fitness_goal=fitness_goal)

        fitness_level = self.request.query_params.get('fitness_level')
        if fitness_level:
            qs = qs.filter(fitness_level=fitness_level)

        gender = self.request.query_params.get('gender')
        if gender:
            qs = qs.filter(gender=gender)

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            active_bool = is_active.lower() in ('true', '1', 'yes')
            qs = qs.filter(user__is_active=active_bool)

        # ── Ordering ─────────────────────────────────────────────────────────
        ordering = self.request.query_params.get('ordering', '-created_at')
        valid_orderings = {
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'full_name': 'user__first_name',
            '-full_name': '-user__first_name',
        }
        qs = qs.order_by(valid_orderings.get(ordering, '-created_at'))

        return qs

    def create(self, request, *args, **kwargs):
        serializer = MemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(
            MemberProfileSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Member Retrieve / Update / Delete ────────────────────────────────────────

class MemberDetailView(APIView):
    """
    GET    /api/members/<id>/   — Retrieve (Owner/Staff/Trainer, or self)
    PATCH  /api/members/<id>/   — Partial update (Owner/Staff, or self updating own profile)
    PUT    /api/members/<id>/   — Full update (Owner/Staff only)
    DELETE /api/members/<id>/   — Soft-delete / deactivate (Owner/Staff only)
    """
    permission_classes = [IsAuthenticated]

    def _get_profile(self, pk):
        return get_profile_or_404(pk)

    def _can_read(self, request, profile):
        """Owner, Staff, Trainer can read any profile. Member can only read their own."""
        if request.user.role in (
            User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER
        ):
            return True
        return profile.user == request.user

    def _can_write(self, request, profile):
        """Owner/Staff can update any profile. Member can update their own."""
        if request.user.role in (User.Role.OWNER, User.Role.STAFF):
            return True
        return profile.user == request.user

    def _can_delete(self, request):
        """Only Owner/Staff can deactivate a member."""
        return request.user.role in (User.Role.OWNER, User.Role.STAFF)

    def get(self, request, pk):
        profile = self._get_profile(pk)
        if not self._can_read(request, profile):
            raise PermissionDenied('You do not have permission to view this profile.')
        return Response(MemberProfileSerializer(profile).data)

    def patch(self, request, pk):
        profile = self._get_profile(pk)
        if not self._can_write(request, profile):
            raise PermissionDenied('You do not have permission to update this profile.')
        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile).data)

    def put(self, request, pk):
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can perform full profile updates.')
        profile = self._get_profile(pk)
        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile).data)

    def delete(self, request, pk):
        if not self._can_delete(request):
            raise PermissionDenied('Only Owner/Staff can deactivate members.')
        profile = self._get_profile(pk)
        user = profile.user
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response(
            {'detail': f'Member {user.get_full_name()} has been deactivated.'},
            status=status.HTTP_200_OK,
        )


# ─── Member Reactivate ─────────────────────────────────────────────────────────

class MemberReactivateView(APIView):
    """
    POST /api/members/<id>/reactivate/  — Reactivate a deactivated member (Owner/Staff only).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can reactivate members.')
        profile = get_profile_or_404(pk)
        user = profile.user
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response(MemberProfileSerializer(profile).data)


# ─── Member's Own Profile ─────────────────────────────────────────────────────

class MyProfileView(APIView):
    """
    GET   /api/members/me/  — Retrieve own member profile.
    PATCH /api/members/me/  — Update own member profile fields.

    Only accessible by users with role=MEMBER.
    """
    permission_classes = [IsAuthenticated]

    def _get_own_profile(self, user):
        try:
            return MemberProfile.objects.select_related('user').get(user=user)
        except MemberProfile.DoesNotExist:
            raise NotFound('Member profile not found for your account.')

    def get(self, request):
        if not request.user.is_member:
            raise PermissionDenied('This endpoint is for members only.')
        profile = self._get_own_profile(request.user)
        return Response(MemberProfileSerializer(profile).data)

    def patch(self, request):
        if not request.user.is_member:
            raise PermissionDenied('This endpoint is for members only.')
        profile = self._get_own_profile(request.user)
        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile).data)