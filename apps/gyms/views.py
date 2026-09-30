import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwner, IsOwnerOrStaff, subscription_allowed
from apps.accounts.tokens import token_for_membership
from apps.gyms.models import AuditLog, Branch, Gym, GymMembership, ImpersonationSession, Invitation
from apps.gyms.serializers import (
    GymMembershipCreateSerializer,
    GymMembershipSerializer,
    GymMembershipUpdateSerializer,
    GymSerializer,
    InvitationSerializer,
)
from apps.gyms.services import record_audit
from apps.gyms.trash_views import TrashListView, TrashPurgeView, TrashRestoreView, TrashSummaryView
from apps.gyms.role_views import CustomRoleDetailView, CustomRoleListCreateView, RoleCatalogView

User = get_user_model()


class GymListView(generics.ListAPIView):
    serializer_class = GymSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Gym.objects.filter(
            memberships__user=self.request.user,
            memberships__status=GymMembership.Status.ACTIVE,
            status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).distinct()


class CurrentGymView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'No active gym membership.'}, status=404)
        data = GymSerializer(gym).data
        branch = getattr(request, 'branch', None)
        if branch is not None:
            data['branch'] = {
                'id': branch.id,
                'name': branch.name,
                'code': branch.code,
            }
        else:
            data['branch'] = None
        if getattr(request, 'gym_role', None) == GymMembership.Role.OWNER:
            accessible_branches = gym.branches.filter(status=Branch.Status.ACTIVE)
        else:
            accessible_branches = [access.branch for access in request.branch_memberships]
        data['branches'] = [
            {'id': item.id, 'name': item.name, 'code': item.code}
            for item in accessible_branches
        ]
        return Response(data)


class GymDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        membership = GymMembership.objects.filter(
            gym_id=pk,
            user=request.user,
            status=GymMembership.Status.ACTIVE,
            gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).select_related('gym').first()
        if membership is None:
            return Response({'detail': 'Gym not found.'}, status=404)
        return Response(GymSerializer(membership.gym).data)


class GymMembershipListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        membership = GymMembership.objects.filter(
            gym_id=pk,
            user=request.user,
            status=GymMembership.Status.ACTIVE,
            gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).first()
        if membership is None:
            return Response({'detail': 'Gym not found.'}, status=404)
        if membership.role not in (GymMembership.Role.OWNER, GymMembership.Role.STAFF):
            return Response({'detail': 'Owner or Staff access required.'}, status=403)
        rows = GymMembership.objects.filter(gym_id=pk).select_related('user', 'gym')
        return Response(GymMembershipSerializer(rows, many=True).data)

    @transaction.atomic
    def post(self, request, pk):
        gym = Gym.objects.filter(pk=pk).first()
        actor = GymMembership.objects.filter(
            gym=gym, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).select_related('gym').first()
        if actor is None or actor.role not in (GymMembership.Role.OWNER, GymMembership.Role.STAFF):
            return Response({'detail': 'Owner or Staff access required.'}, status=403)
        if actor.role == GymMembership.Role.OWNER and not subscription_allowed(request, gym=actor.gym, role=actor.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        serializer = GymMembershipCreateSerializer(
            data=request.data,
            context={'request': request, 'gym': gym},
        )
        serializer.is_valid(raise_exception=True)
        if actor.role == GymMembership.Role.STAFF and serializer.validated_data['role'] == GymMembership.Role.OWNER:
            return Response({'role': ['Staff cannot create another owner.']}, status=403)
        membership = serializer.save()
        record_audit(
            gym=gym,
            actor=request.user,
            action='gym.membership.created',
            request=request,
            target=membership,
            metadata={'role': membership.role},
        )
        return Response(GymMembershipSerializer(membership).data, status=201)


class GymMembershipDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _actor(self, request, gym_id):
        return GymMembership.objects.select_related('gym').filter(
            gym_id=gym_id,
            user=request.user,
            status=GymMembership.Status.ACTIVE,
            gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).first()

    def patch(self, request, pk, membership_id):
        actor = self._actor(request, pk)
        if actor is None or actor.role not in (GymMembership.Role.OWNER, GymMembership.Role.STAFF):
            return Response({'detail': 'Owner or Staff access required.'}, status=403)
        if actor.role == GymMembership.Role.OWNER and not subscription_allowed(request, gym=actor.gym, role=actor.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        membership = GymMembership.objects.filter(
            pk=membership_id,
            gym_id=pk,
        ).select_related('user', 'gym').first()
        if membership is None:
            return Response({'detail': 'Gym membership not found.'}, status=404)
        if actor.role == GymMembership.Role.STAFF and (
            membership.role == GymMembership.Role.OWNER
            or request.data.get('role') == GymMembership.Role.OWNER
        ):
            return Response({'detail': 'Staff cannot modify or create an owner membership.'}, status=403)
        if membership.role == GymMembership.Role.OWNER:
            owner_count = GymMembership.objects.filter(
                gym_id=pk,
                role=GymMembership.Role.OWNER,
                status=GymMembership.Status.ACTIVE,
            ).exclude(pk=membership.pk).count()
            requested_role = request.data.get('role', membership.role)
            requested_status = request.data.get('status', membership.status)
            if owner_count == 0 and (
                requested_role != GymMembership.Role.OWNER
                or requested_status != GymMembership.Status.ACTIVE
            ):
                return Response({'detail': 'A gym must retain at least one active owner.'}, status=400)
        serializer = GymMembershipUpdateSerializer(
            membership,
            data=request.data,
            partial=True,
            context={'gym': membership.gym, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        if membership.role == GymMembership.Role.MEMBER:
            from apps.members.models import MemberProfile
            profile_branch = (
                membership.branch_memberships.select_related('branch')
                .filter(branch__status=Branch.Status.ACTIVE)
                .first()
            )
            profile = MemberProfile._base_manager.filter(
                user=membership.user, gym=membership.gym,
            ).first()
            if profile is None:
                profile = MemberProfile._base_manager.filter(
                    user=membership.user, gym__isnull=True,
                ).first()
            if profile is None:
                MemberProfile._base_manager.create(
                    user=membership.user,
                    gym=membership.gym,
                    branch=profile_branch.branch if profile_branch else None,
                )
            elif profile.gym_id is None:
                profile.gym = membership.gym
                profile.branch = profile_branch.branch if profile_branch else None
                profile.save(update_fields=['gym', 'branch', 'updated_at'])
            elif profile.is_deleted:
                # Re-adding a member revives their trashed profile.
                profile.restore()
        elif membership.role == GymMembership.Role.STAFF:
            from apps.staff.models import StaffProfile
            StaffProfile._base_manager.get_or_create(
                user=membership.user,
                gym=membership.gym,
                defaults={'branch': membership.branch_memberships.first().branch if membership.branch_memberships.exists() else None},
            )
        elif membership.role == GymMembership.Role.TRAINER:
            from apps.trainers.models import TrainerProfile
            TrainerProfile._base_manager.get_or_create(
                user=membership.user,
                gym=membership.gym,
                defaults={'branch': membership.branch_memberships.first().branch if membership.branch_memberships.exists() else None},
            )
        record_audit(
            gym=membership.gym,
            actor=request.user,
            action='gym.membership.updated',
            request=request,
            target=membership,
            metadata={
                'role': membership.role,
                'status': membership.status,
            },
        )
        return Response(GymMembershipSerializer(membership).data)


class GymSwitchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request, 'impersonation_session', None) is not None:
            return Response({'detail': 'Gym switching is not available during impersonation.'}, status=403)
        gym_id = request.data.get('gym_id')
        try:
            gym_id = int(gym_id)
        except (TypeError, ValueError):
            return Response({'gym_id': 'Enter a valid gym ID.'}, status=400)
        membership = GymMembership.objects.filter(
            gym_id=gym_id,
            user=request.user,
            status=GymMembership.Status.ACTIVE,
            gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).select_related('gym').first()
        if membership is None:
            return Response({'detail': 'Active gym membership not found.'}, status=404)
        refresh = token_for_membership(request.user, membership)
        refresh['gym_id'] = membership.gym_id
        refresh['gym_role'] = membership.role
        refresh['gym_public_id'] = membership.gym.public_id
        refresh['role'] = membership.role
        refresh['token_version'] = request.user.token_version
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'gym': GymSerializer(membership.gym).data,
            'role': membership.role,
        })


class BranchListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        membership = GymMembership.objects.filter(
            gym_id=pk, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).first()
        if membership is None:
            return Response({'detail': 'Gym not found.'}, status=404)
        if membership.role not in (GymMembership.Role.OWNER, GymMembership.Role.STAFF):
            return Response({'detail': 'Owner or Staff access required.'}, status=403)
        branches = Branch.objects.filter(gym_id=pk).order_by('-is_primary', 'name')
        return Response([
            {'id': b.id, 'name': b.name, 'code': b.code, 'address': b.address,
             'phone': b.phone, 'status': b.status, 'is_primary': b.is_primary}
            for b in branches
        ])

    @transaction.atomic
    def post(self, request, pk):
        membership = GymMembership.objects.filter(
            gym_id=pk, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).first()
        if membership is None or membership.role != GymMembership.Role.OWNER:
            return Response({'detail': 'Owner access required.'}, status=403)
        if not subscription_allowed(request, gym=membership.gym, role=membership.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        name = str(request.data.get('name', '')).strip()
        code = str(request.data.get('code', '')).strip().upper()
        if not name or not code:
            return Response({'detail': 'name and code are required.'}, status=400)
        branch, created = Branch.objects.get_or_create(
            gym_id=pk,
            code=code,
            defaults={
                'name': name,
                'address': request.data.get('address', ''),
                'phone': request.data.get('phone', ''),
            },
        )
        record_audit(gym=membership.gym, actor=request.user, action='gym.branch.created', request=request, target=branch)
        return Response({
            'id': branch.id, 'name': branch.name, 'code': branch.code,
            'status': branch.status, 'is_primary': branch.is_primary,
        }, status=201 if created else 200)


class InvitationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        membership = GymMembership.objects.select_related('gym').filter(
            gym_id=pk, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).first()
        if membership is None or membership.role not in (GymMembership.Role.OWNER, GymMembership.Role.STAFF):
            return Response({'detail': 'Owner or Staff access required.'}, status=403)
        if membership.role == GymMembership.Role.OWNER and not subscription_allowed(request, gym=membership.gym, role=membership.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        gym = membership.gym
        email = str(request.data.get('email', '')).strip().lower()
        role = request.data.get('role')
        if not email or not role:
            return Response({'detail': 'email and role are required.'}, status=400)
        existing = Invitation.objects.select_for_update().filter(
            gym=gym,
            email=email,
            role=role,
            status=Invitation.Status.PENDING,
            expires_at__gt=timezone.now(),
        ).first()
        if existing is not None:
            return Response(
                {'detail': 'A pending invitation already exists for this email and role.'},
                status=409,
            )
        serializer = InvitationSerializer(
            data={**request.data, 'email': email},
            context={'request': request, 'gym': gym},
        )
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()
        record_audit(
            gym=gym,
            actor=request.user,
            action='gym.invitation.created',
            request=request,
            target=invitation,
            metadata={'role': invitation.role},
        )
        return Response(serializer.data, status=201)


class InvitationAcceptView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        import hashlib

        token = str(request.data.get('token', '')).strip()
        if not token:
            return Response({'detail': 'Invitation token is required.'}, status=400)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invitation = Invitation.objects.select_for_update().filter(
            token_hash=token_hash,
        ).first()
        if invitation is None or not invitation.is_valid:
            return Response({'detail': 'Invitation is invalid or expired.'}, status=400)
        if invitation.gym.status not in (Gym.Status.ACTIVE, Gym.Status.TRIAL):
            return Response({'detail': 'This gym is not accepting invitations.'}, status=403)
        if invitation.branch and (
            invitation.branch.gym_id != invitation.gym_id
            or invitation.branch.status != Branch.Status.ACTIVE
        ):
            return Response({'detail': 'Invitation branch is invalid.'}, status=400)

        email = invitation.email
        password = str(request.data.get('password', ''))
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            current_password = str(request.data.get('current_password', ''))
            if not current_password or not user.check_password(current_password):
                return Response(
                    {'current_password': 'Confirm the existing account password to accept this invitation.'},
                    status=400,
                )
            if not user.is_active:
                return Response({'detail': 'This account is inactive.'}, status=403)
            had_membership = GymMembership.objects.filter(user=user).exists()
        else:
            if not password:
                return Response({'password': 'This field is required.'}, status=400)
            try:
                validate_password(password)
            except Exception as exc:
                return Response({'password': getattr(exc, 'messages', [str(exc)])}, status=400)
            user = User(
                email=email,
                first_name=request.data.get('first_name', 'Member'),
                last_name=request.data.get('last_name', 'User'),
                role=invitation.role,
            )
            user.set_password(password)
            user.save()
            had_membership = False

        membership = GymMembership.objects.select_for_update().filter(
            user=user,
            gym=invitation.gym,
        ).first()
        if membership is None:
            membership = GymMembership.objects.create(
                user=user,
                gym=invitation.gym,
                role=invitation.role,
                status=GymMembership.Status.ACTIVE,
            )
        elif membership.status != GymMembership.Status.ACTIVE:
            membership.status = GymMembership.Status.ACTIVE
            membership.save(update_fields=['status', 'updated_at'])

        branch = invitation.branch
        if branch is None:
            from apps.gyms.services import primary_branch
            branch = primary_branch(invitation.gym)
        if branch:
            membership.branch_memberships.get_or_create(branch=branch)
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
        if not user.gym_memberships.filter(is_default=True).exists():
            membership.is_default = True
            membership.save(update_fields=['is_default', 'updated_at'])
        if membership.role == GymMembership.Role.MEMBER:
            from apps.members.models import MemberProfile
            profile = MemberProfile._base_manager.filter(
                user=user, gym=invitation.gym,
            ).first()
            if profile is None:
                profile = MemberProfile._base_manager.filter(
                    user=user, gym__isnull=True,
                ).first()
            if profile is None:
                MemberProfile._base_manager.create(
                    user=user, gym=invitation.gym, branch=branch,
                )
            elif profile.gym_id is None:
                profile.gym = invitation.gym
                profile.branch = branch
                profile.save(update_fields=['gym', 'branch', 'updated_at'])
            elif profile.is_deleted:
                # Accepting an invitation revives a trashed profile.
                profile.restore()
        elif membership.role == GymMembership.Role.STAFF:
            from apps.staff.models import StaffProfile
            StaffProfile._base_manager.get_or_create(
                user=user,
                gym=invitation.gym,
                defaults={'branch': branch},
            )
        elif membership.role == GymMembership.Role.TRAINER:
            from apps.trainers.models import TrainerProfile
            TrainerProfile._base_manager.get_or_create(
                user=user,
                gym=invitation.gym,
                defaults={'branch': branch},
            )
        if not had_membership:
            user.role = invitation.role
            user.save(update_fields=['role'])

        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_user = user
        invitation.save(update_fields=['status', 'accepted_at', 'accepted_user'])
        record_audit(
            gym=invitation.gym,
            actor=user,
            action='gym.invitation.accepted',
            request=request,
            target=invitation,
            metadata={'role': membership.role},
        )
        refresh = token_for_membership(user, membership)
        refresh['gym_id'] = invitation.gym_id
        refresh['gym_role'] = membership.role
        refresh['gym_public_id'] = invitation.gym.public_id
        refresh['token_version'] = user.token_version
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user_id': user.id,
            'gym_id': invitation.gym_id,
            'role': membership.role,
        })


class ImpersonationStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        actor_membership = GymMembership.objects.filter(
            gym_id=pk, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).first()
        try:
            subject_user_id = int(request.data.get('user_id'))
        except (TypeError, ValueError):
            return Response({'user_id': 'Enter a valid user ID.'}, status=400)
        subject_membership = GymMembership.objects.filter(
            gym_id=pk, role__in=[GymMembership.Role.STAFF, GymMembership.Role.TRAINER, GymMembership.Role.MEMBER],
            status=GymMembership.Status.ACTIVE,
            gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL],
        ).select_related('user', 'gym').filter(user_id=subject_user_id).first()
        if actor_membership is None or actor_membership.role != GymMembership.Role.OWNER:
            return Response({'detail': 'Owner access required.'}, status=403)
        if not subscription_allowed(request, gym=actor_membership.gym, role=actor_membership.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        if subject_membership is None:
            return Response({'detail': 'Target gym membership not found.'}, status=404)
        reason = str(request.data.get('reason', '')).strip()
        if not reason:
            return Response({'reason': 'A reason is required.'}, status=400)
        session = ImpersonationSession.objects.create(
            gym=actor_membership.gym,
            actor=request.user,
            subject=subject_membership.user,
            reason=reason,
            jti=uuid.uuid4().hex,
            expires_at=timezone.now() + timedelta(minutes=15),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
        token = token_for_membership(subject_membership.user, subject_membership)
        session.jti = token.payload['jti']
        session.save(update_fields=['jti'])
        token['gym_id'] = actor_membership.gym_id
        token['gym_role'] = subject_membership.role
        token['gym_public_id'] = actor_membership.gym.public_id
        token['role'] = subject_membership.role
        token['token_version'] = subject_membership.user.token_version
        token['actor_id'] = request.user.id
        token['impersonation_id'] = session.id
        record_audit(
            gym=actor_membership.gym,
            actor=request.user,
            action='impersonation.started',
            request=request,
            target=subject_membership.user,
            metadata={'reason': reason, 'session_id': session.id},
        )
        return Response({
            'access': str(token.access_token),
            'refresh': str(token),
            'session_id': session.id,
            'subject': {'id': subject_membership.user_id, 'display_id': subject_membership.user.display_id},
            'expires_at': session.expires_at,
        })


class ImpersonationEndView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        session = ImpersonationSession.objects.filter(pk=pk).first()
        if session is None:
            return Response({'detail': 'Session not found.'}, status=404)
        if session.actor_id != request.user.id and session.subject_id != request.user.id:
            return Response({'detail': 'You cannot end this session.'}, status=403)
        if session.ended_at is None:
            session.ended_at = timezone.now()
            session.save(update_fields=['ended_at'])
            record_audit(gym=session.gym, actor=request.user, action='impersonation.ended', request=request, target=session)
        return Response({'detail': 'Impersonation session ended.'})


class AuditLogListView(generics.ListAPIView):
    serializer_class = None
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        membership = GymMembership.objects.filter(
            gym_id=pk, user=request.user, status=GymMembership.Status.ACTIVE, gym__status__in=[Gym.Status.ACTIVE, Gym.Status.TRIAL]
        ).first()
        if membership is None or membership.role != GymMembership.Role.OWNER:
            return Response({'detail': 'Owner access required.'}, status=403)
        if not subscription_allowed(request, gym=membership.gym, role=membership.role):
            return Response({'detail': 'An active gym subscription is required.'}, status=402)
        rows = AuditLog.objects.filter(gym_id=pk).select_related('actor')[:200]
        return Response([
            {'id': row.id, 'action': row.action, 'actor': row.actor.get_full_name() if row.actor else None,
             'target_type': row.target_type, 'target_id': row.target_id,
             'metadata': row.metadata, 'created_at': row.created_at}
            for row in rows
        ])
