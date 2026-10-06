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
    POST   /api/members/bulk-delete/      - Bulk-delete members into Trash (Owner/Admin)
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
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import generics, status, filters
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrTrainer
from apps.gyms.tenancy import tenant_queryset
from apps.members.models import MemberProfile
from apps.members.serializers import (
    MemberAggregatedProfileSerializer,
    MemberCreateSerializer,
    MemberListSerializer,
    MemberProfileSerializer,
    MemberProfileUpdateSerializer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_profile_or_404(pk):
    try:
        return MemberProfile.objects.select_related('user').get(pk=pk)
    except MemberProfile.DoesNotExist:
        raise NotFound(f'Member profile with id={pk} not found.')


def deactivate_and_trash(profile, actor, gym):
    """Deactivate a member's login and move their profile to Trash.

    Shared by the single DELETE and the bulk-delete endpoints so both leave
    the same recoverable trace: the profile is soft-deleted (visible in Trash,
    restorable from there) and the account is switched off while the member
    has no other active gym membership.
    """
    from apps.gyms.models import GymMembership
    user = profile.user
    if gym is not None:
        GymMembership.objects.filter(
            user=user,
            gym=gym,
            role=GymMembership.Role.MEMBER,
            status=GymMembership.Status.ACTIVE,
        ).update(status=GymMembership.Status.INACTIVE)
        still_member_somewhere = user.gym_memberships.filter(
            status=GymMembership.Status.ACTIVE,
        ).exists()
    else:
        still_member_somewhere = False
    if not still_member_somewhere:
        user.is_active = False
        user.save(update_fields=['is_active'])
    profile.delete(user=actor)


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

        qs = MemberProfile.objects.select_related('user')
        if getattr(self.request, 'gym', None) is not None:
            qs = qs.filter(
                user__gym_memberships__gym=self.request.gym,
                user__gym_memberships__role=User.Role.MEMBER,
                user__gym_memberships__status='ACTIVE',
            )
        else:
            qs = qs.filter(user__role=User.Role.MEMBER)
        qs = qs.prefetch_related(
            Prefetch(
                'user__memberships',
                queryset=Membership.objects.exclude(status='CANCELLED').select_related('plan'),
                to_attr='_current_memberships',
            )
        )
        qs = tenant_queryset(qs, self.request)

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
        serializer = MemberCreateSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(
            MemberProfileSerializer(profile, context={'request': request}).data,
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
        if getattr(request, 'gym', None) is not None and profile.gym_id != request.gym.id:
            return False
        role = getattr(request, 'gym_role', request.user.role)
        if role in (
            User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER
        ):
            return True
        return profile.user == request.user

    def _can_write(self, request, profile):
        """Owner/Staff can update any profile. Member can update their own."""
        if getattr(request, 'gym', None) is not None and profile.gym_id != request.gym.id:
            return False
        if getattr(request, 'gym_role', request.user.role) in (User.Role.OWNER, User.Role.STAFF):
            return True
        return profile.user == request.user

    def _can_delete(self, request):
        """Only Owner/Staff can deactivate a member."""
        return getattr(request, 'gym_role', request.user.role) in (User.Role.OWNER, User.Role.STAFF)

    def get(self, request, pk):
        profile = self._get_profile(pk)
        if not self._can_read(request, profile):
            raise PermissionDenied('You do not have permission to view this profile.')
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)

    def patch(self, request, pk):
        profile = self._get_profile(pk)
        if not self._can_write(request, profile):
            raise PermissionDenied('You do not have permission to update this profile.')

        # profile_picture lives on User, not MemberProfile — handle it separately
        if 'profile_picture' in request.FILES:
            user = profile.user
            user.profile_picture = request.FILES['profile_picture']
            user.save(update_fields=['profile_picture'])

        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)

    def put(self, request, pk):
        if getattr(request, 'gym_role', request.user.role) not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can perform full profile updates.')
        profile = self._get_profile(pk)

        # profile_picture lives on User, not MemberProfile — handle it separately
        if 'profile_picture' in request.FILES:
            user = profile.user
            user.profile_picture = request.FILES['profile_picture']
            user.save(update_fields=['profile_picture'])

        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)

    def delete(self, request, pk):
        if not self._can_delete(request):
            raise PermissionDenied('Only Owner/Staff can deactivate members.')
        profile = self._get_profile(pk)
        user = profile.user
        # Deactivate the login and soft-delete the profile → recoverable from Trash.
        deactivate_and_trash(profile, actor=request.user, gym=getattr(request, 'gym', None))
        return Response(
            {'detail': f'Member {user.get_full_name()} has been deactivated and moved to trash.'},
            status=status.HTTP_200_OK,
        )


# ─── Member Bulk Delete (hybrid) ──────────────────────────────────────────────

class MemberBulkDeleteView(APIView):
    """
    POST /api/members/bulk-delete/ — Bulk-delete members into Trash (Owner/Admin only).

    Body: {"ids": [<user_id>, ...]}

    Per id (each wrapped in its own savepoint so one failure never aborts the batch):
      1. Not a member of this gym / role != MEMBER / superuser / the requesting
         user -> skipped.
      2. Profile already in Trash -> skipped.
      3. Otherwise -> the login is switched off and the profile is soft-deleted,
         i.e. moved to Trash, from where it can be restored.

    Response: {"trashed": n, "deactivated": n, "skipped": [{"id", "reason"}]}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in (User.Role.OWNER, User.Role.ADMIN):
            raise PermissionDenied('Only Owners/Admins can bulk delete members.')

        raw_ids = request.data.get('ids')
        if not isinstance(raw_ids, list):
            return Response(
                {'detail': 'Request body must include an "ids" list.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        skipped = []
        ids = []
        seen = set()
        for raw in raw_ids:
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                skipped.append({'id': raw, 'reason': 'not a deletable member'})
                continue
            if pk in seen:
                continue
            seen.add(pk)
            ids.append(pk)

        # One query for the whole batch. all_objects (not objects) so profiles
        # already sitting in Trash are recognised instead of re-processed; the
        # manager plus the explicit filter keep the batch inside this gym.
        gym = getattr(request, 'gym', None)
        profiles = MemberProfile.all_objects.select_related('user').filter(user_id__in=ids)
        if gym is not None:
            profiles = profiles.filter(gym=gym)
        profiles_by_user = {p.user_id: p for p in profiles}

        trashed = deactivated = 0
        with transaction.atomic():
            for pk in ids:
                profile = profiles_by_user.get(pk)
                user = profile.user if profile is not None else None
                if (
                    user is None
                    or user.role != User.Role.MEMBER
                    or user.is_superuser
                    or user.id == request.user.id
                ):
                    skipped.append({'id': pk, 'reason': 'not a deletable member'})
                    continue
                if profile.is_deleted:
                    skipped.append({'id': pk, 'reason': 'already in trash'})
                    continue
                try:
                    with transaction.atomic():
                        was_active = user.is_active
                        deactivate_and_trash(profile, actor=request.user, gym=gym)
                        trashed += 1
                        if was_active:
                            deactivated += 1
                except Exception:
                    logger.exception('Bulk delete failed for member user id=%s', pk)
                    skipped.append({'id': pk, 'reason': 'could not be deleted'})

        return Response(
            {'trashed': trashed, 'deactivated': deactivated, 'skipped': skipped},
            status=status.HTTP_200_OK,
        )


# ─── Member Reactivate ─────────────────────────────────────────────────────────

class MemberReactivateView(APIView):
    """
    POST /api/members/<id>/reactivate/  — Reactivate a deactivated member (Owner/Staff only).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if getattr(request, 'gym_role', request.user.role) not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can reactivate members.')
        # Fetch from all_objects: a soft-deleted profile is exactly the row
        # this endpoint exists to bring back — the live manager would 404 it.
        profile = MemberProfile.all_objects.select_related('user').filter(pk=pk).first()
        if profile is None:
            raise NotFound(f'Member profile with id={pk} not found.')
        if getattr(request, 'gym', None) is not None and profile.gym_id != request.gym.id:
            raise PermissionDenied('You do not have access to this member.')
        # Revive the profile if it was soft-deleted (trash recovery path).
        if profile.is_deleted:
            profile.restore(user=request.user)
        user = profile.user
        gym = getattr(request, 'gym', None)
        if gym is not None:
            from apps.gyms.models import GymMembership
            membership, _ = GymMembership.objects.update_or_create(
                user=user,
                gym=gym,
                defaults={
                    'role': GymMembership.Role.MEMBER,
                    'status': GymMembership.Status.ACTIVE,
                },
            )
            branch = profile.branch
            if branch:
                membership.branch_memberships.get_or_create(branch=branch)
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=['is_active'])
        else:
            user.is_active = True
            user.save(update_fields=['is_active'])
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)


# ─── Member's Own Profile ─────────────────────────────────────────────────────

class MyProfileView(APIView):
    """
    GET   /api/members/me/  — Retrieve own member profile.
    PATCH /api/members/me/  — Update own member profile fields.

    Only accessible by users with role=MEMBER.
    """
    permission_classes = [IsAuthenticated]

    def _get_own_profile(self, user, request=None):
        try:
            qs = MemberProfile.objects.select_related('user').filter(user=user)
            if request is not None:
                qs = tenant_queryset(qs, request)
            return qs.first()
        except MemberProfile.DoesNotExist:
            raise NotFound('Member profile not found for your account.')

    def get(self, request):
        if getattr(request, 'gym_role', request.user.role) != User.Role.MEMBER:
            raise PermissionDenied('This endpoint is for members only.')
        profile = self._get_own_profile(request.user, request)
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)

    def patch(self, request):
        if getattr(request, 'gym_role', request.user.role) != User.Role.MEMBER:
            raise PermissionDenied('This endpoint is for members only.')
        profile = self._get_own_profile(request.user, request)

        # profile_picture lives on User
        if 'profile_picture' in request.FILES:
            request.user.profile_picture = request.FILES['profile_picture']
            request.user.save(update_fields=['profile_picture'])

        serializer = MemberProfileUpdateSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberProfileSerializer(profile, context={'request': request}).data)


# ─── Aggregated Member Profile Detail ─────────────────────────────────────────

class MemberProfileDetailView(APIView):
    """
    GET /api/members/<id>/profile-detail/ — Aggregated profile for the detail page.
    Returns member profile + membership, attendance, trainer, workouts, diet, progress, payments.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        profile = get_profile_or_404(pk)
        if getattr(request, 'gym', None) is not None and profile.gym_id != request.gym.id:
            raise PermissionDenied('You do not have access to this profile.')
        if not (getattr(request, 'gym_role', request.user.role) in (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER)
                or profile.user == request.user):
            raise PermissionDenied('You do not have permission to view this profile.')
        return Response(MemberAggregatedProfileSerializer(profile, context={'request': request}).data)