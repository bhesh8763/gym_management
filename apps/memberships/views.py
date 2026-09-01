"""
Views for the Memberships app.

API Endpoints:
    GET/POST              /api/memberships/plans/            - List/create plans (Owner/Staff create)
    GET/PUT/PATCH/DELETE   /api/memberships/plans/<id>/       - Manage a plan (DELETE deactivates)

    GET/POST               /api/memberships/                 - List/assign memberships
    GET                    /api/memberships/expiring/         - Active memberships ending soon (?days=7)
    GET/PATCH/DELETE       /api/memberships/<id>/             - Retrieve/update/cancel
    POST                   /api/memberships/<id>/freeze/      - Freeze (hold) a membership
    POST                   /api/memberships/<id>/unfreeze/    - Resume a frozen membership
    POST                   /api/memberships/<id>/renew/       - Renew into a new membership record

Search/Filter (list):
    ?search=<member name|email>
    ?status=<ACTIVE|EXPIRED|FROZEN|CANCELLED|PENDING>
    ?plan=<plan id>
    ?member=<member id>
    ?ordering=<start_date|-start_date|end_date|-end_date|created_at|-created_at>
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsMember, IsOwnerOrStaff, IsOwnerOrStaffOrTrainer
from apps.notifications.models import Notification
from apps.memberships.models import FreezeRequest, Membership, MembershipPlan
from apps.memberships.serializers import (
    FreezeRequestCreateSerializer,
    FreezeRequestListSerializer,
    FreezeSerializer,
    MembershipCreateSerializer,
    MembershipDetailSerializer,
    MembershipListSerializer,
    MembershipPlanSerializer,
    MembershipUpdateSerializer,
    RenewSerializer,
)

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sync_expired(qs):
    """
    Flip ACTIVE memberships whose end_date has passed to EXPIRED.
    Short-circuits with a cheap EXISTS check before issuing any UPDATE,
    so list views that have no stale memberships pay only one fast query.
    """
    today = timezone.now().date()
    stale = qs.filter(status=Membership.Status.ACTIVE, end_date__lt=today)
    if stale.exists():
        stale.update(status=Membership.Status.EXPIRED)


def get_membership_or_404(pk):
    try:
        return Membership.objects.select_related('member', 'plan').get(pk=pk)
    except Membership.DoesNotExist:
        raise NotFound(f'Membership with id={pk} not found.')


# ─── Plans ──────────────────────────────────────────────────────────────────

class PlanListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/memberships/plans/  — any authenticated user (needed to choose a plan)
    POST /api/memberships/plans/  — Owner/Staff only
    """
    serializer_class = MembershipPlanSerializer
    queryset = MembershipPlan.objects.all().order_by('price')

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('true', '1', 'yes'))
        return qs


class PlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET               — any authenticated user
    PUT/PATCH/DELETE  — Owner/Staff only

    DELETE deactivates rather than hard-deletes, since plans are protected
    (on_delete=PROTECT) by any membership that has ever used them.
    """
    serializer_class = MembershipPlanSerializer
    queryset = MembershipPlan.objects.all()

    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsOwnerOrStaff()]

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.is_active = False
        plan.save(update_fields=['is_active'])
        return Response(
            {'detail': f'Plan "{plan.name}" deactivated.'}, status=status.HTTP_200_OK
        )


# ─── Memberships: list + create ────────────────────────────────────────────────

class MembershipListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/memberships/  — Owner/Staff/Trainer see all, Member sees only their own
    POST /api/memberships/  — Owner/Staff assign a plan to a member,
                              Member self-purchase (auto-sets member + PENDING status)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MembershipCreateSerializer
        return MembershipListSerializer

    def get_queryset(self):
        qs = Membership.objects.select_related('member', 'plan')
        _sync_expired(qs)

        user = self.request.user
        if user.role == User.Role.MEMBER:
            qs = qs.filter(member=user)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(member__first_name__icontains=search) |
                Q(member__last_name__icontains=search) |
                Q(member__email__icontains=search)
            )

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        plan_param = self.request.query_params.get('plan')
        if plan_param:
            qs = qs.filter(plan_id=plan_param)

        member_param = self.request.query_params.get('member')
        if member_param:
            qs = qs.filter(member_id=member_param)

        ordering = self.request.query_params.get('ordering', '-start_date')
        valid_orderings = {'start_date', '-start_date', 'end_date', '-end_date', 'created_at', '-created_at'}
        qs = qs.order_by(ordering if ordering in valid_orderings else '-start_date')

        return qs

    def create(self, request, *args, **kwargs):
        user = request.user
        is_self_purchase = user.role == User.Role.MEMBER

        if is_self_purchase:
            data = request.data.copy()
            data['member'] = user.id
            data['status'] = Membership.Status.PENDING
            serializer = MembershipCreateSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            membership = serializer.save()
        else:
            serializer = MembershipCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            membership = serializer.save()

        return Response(
            MembershipDetailSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Memberships: detail / update / cancel ────────────────────────────────────

class MembershipDetailView(APIView):
    """
    GET    — Owner/Staff/Trainer, or the member themselves
    PATCH  — Owner/Staff only (notes, price_paid, end_date, status)
    DELETE — Owner/Staff only, cancels (soft) rather than deletes
    """
    permission_classes = [IsAuthenticated]

    def _can_access(self, request, membership):
        if request.user.role in (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER):
            return True
        return membership.member == request.user

    def get(self, request, pk):
        membership = get_membership_or_404(pk)
        if not self._can_access(request, membership):
            raise PermissionDenied('You do not have permission to view this membership.')
        return Response(MembershipDetailSerializer(membership).data)

    def patch(self, request, pk):
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can update memberships.')
        membership = get_membership_or_404(pk)
        serializer = MembershipUpdateSerializer(membership, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(MembershipDetailSerializer(membership).data)

    def delete(self, request, pk):
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can cancel memberships.')
        membership = get_membership_or_404(pk)
        membership.status = Membership.Status.CANCELLED
        membership.save(update_fields=['status'])
        return Response(
            {'detail': f'Membership #{membership.id} cancelled.'},
            status=status.HTTP_200_OK,
        )


# ─── Freeze / Unfreeze (hold) ──────────────────────────────────────────────────

class MembershipWriteThrottle(UserRateThrottle):
    """Throttle for membership write operations (freeze, unfreeze, renew)."""
    rate = '30/min'
    scope = 'membership-write'


class MembershipFreezeView(APIView):
    """POST /api/memberships/<id>/freeze/ — Owner/Staff only."""
    permission_classes = [IsOwnerOrStaff]
    throttle_classes = [MembershipWriteThrottle]

    def post(self, request, pk):
        membership = get_membership_or_404(pk)
        if membership.status != Membership.Status.ACTIVE:
            raise ValidationError('Only active memberships can be frozen.')

        serializer = FreezeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        membership.status = Membership.Status.FROZEN
        membership.freeze_start = data['freeze_start']
        membership.freeze_end = data['freeze_end']
        membership.freeze_reason = data.get('freeze_reason', '')
        membership.save()
        return Response(MembershipDetailSerializer(membership).data)


class MembershipUnfreezeView(APIView):
    """
    POST /api/memberships/<id>/unfreeze/ — Owner/Staff only.

    Extends end_date by the frozen duration so the member doesn't lose
    the days they paid for while on hold.
    """
    permission_classes = [IsOwnerOrStaff]
    throttle_classes = [MembershipWriteThrottle]

    def post(self, request, pk):
        membership = get_membership_or_404(pk)
        if membership.status != Membership.Status.FROZEN:
            raise ValidationError('Membership is not currently frozen.')

        if membership.freeze_start and membership.freeze_end:
            frozen_days = (membership.freeze_end - membership.freeze_start).days
            membership.end_date += timedelta(days=max(frozen_days, 0))

        membership.status = Membership.Status.ACTIVE
        membership.freeze_start = None
        membership.freeze_end = None
        membership.freeze_reason = ''
        membership.save()
        return Response(MembershipDetailSerializer(membership).data)


# ─── Renew ─────────────────────────────────────────────────────────────────────

class MembershipRenewView(APIView):
    """
    POST /api/memberships/<id>/renew/ — Owner/Staff, or the member themselves
    for their own expired memberships.

    Creates a new Membership row linked via renewed_from, rather than
    mutating the old one, so the renewal history stays intact.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [MembershipWriteThrottle]

    def _can_access(self, request, membership):
        if request.user.role in (User.Role.OWNER, User.Role.STAFF):
            return True
        return membership.member == request.user

    def post(self, request, pk):
        old = get_membership_or_404(pk)
        if not self._can_access(request, old):
            raise PermissionDenied('You do not have permission to renew this membership.')

        user = request.user
        is_self_renewal = user.role == User.Role.MEMBER

        serializer = RenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        today = timezone.now().date()
        start_date = data.get('start_date') or max(old.end_date + timedelta(days=1), today)
        end_date = start_date + timedelta(days=old.plan.duration_days)
        price_paid = data.get('price_paid', old.plan.price)

        new_status = Membership.Status.PENDING if is_self_renewal else Membership.Status.ACTIVE

        new_membership = Membership.objects.create(
            member=old.member,
            plan=old.plan,
            status=new_status,
            start_date=start_date,
            end_date=end_date,
            price_paid=price_paid,
            renewed_from=old,
        )

        if old.status == Membership.Status.ACTIVE:
            old.status = Membership.Status.EXPIRED
            old.save(update_fields=['status'])

        return Response(
            MembershipDetailSerializer(new_membership).data,
            status=status.HTTP_201_CREATED,
        )


# ─── Expiry tracking ────────────────────────────────────────────────────────────

class ExpiringMembershipsView(generics.ListAPIView):
    """
    GET /api/memberships/expiring/?days=7
    Active memberships ending within the given window (default 7 days).
    """
    serializer_class = MembershipListSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        qs = Membership.objects.select_related('member', 'plan')
        _sync_expired(qs)

        try:
            days = int(self.request.query_params.get('days', 7))
        except ValueError:
            days = 7

        today = timezone.now().date()
        return qs.filter(
            status=Membership.Status.ACTIVE,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=days),
        ).order_by('end_date')


# ─── Freeze Requests ──────────────────────────────────────────────────────────

class FreezeRequestViewSet(viewsets.ModelViewSet):
    """
    GET/POST  /api/memberships/freeze-requests/
    GET       /api/memberships/freeze-requests/<id>/
    POST      /api/memberships/freeze-requests/<id>/approve/
    POST      /api/memberships/freeze-requests/<id>/reject/

    Members create requests; Owner/Staff list all and approve/reject.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return FreezeRequestCreateSerializer
        return FreezeRequestListSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in (User.Role.OWNER, User.Role.STAFF):
            qs = FreezeRequest.objects.select_related(
                'membership', 'membership__plan', 'requested_by', 'reviewed_by',
            ).all()
        else:
            qs = FreezeRequest.objects.select_related(
                'membership', 'membership__plan', 'requested_by', 'reviewed_by',
            ).filter(requested_by=user)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        return qs

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        freeze_request = serializer.instance

        # Notify all owner/staff about new freeze request
        from django.contrib.auth import get_user_model
        User = get_user_model()
        staff_users = User.objects.filter(
            role__in=[User.Role.OWNER, User.Role.STAFF], is_active=True
        )
        for staff_user in staff_users:
            Notification.objects.create(
                recipient=staff_user,
                notification_type=Notification.NotificationType.GENERAL,
                title='New freeze request',
                message=(
                    f'{request.user.get_full_name()} requested to freeze their '
                    f'"{freeze_request.membership.plan.name}" membership from '
                    f'{freeze_request.freeze_start} to {freeze_request.freeze_end}.'
                ),
                related_membership_id=freeze_request.membership_id,
            )

        return Response(
            FreezeRequestListSerializer(freeze_request).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Approve a freeze request — freezes the membership."""
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can approve freeze requests.')

        freeze_request = self.get_object()
        if freeze_request.status != FreezeRequest.Status.PENDING:
            raise ValidationError('This request has already been reviewed.')

        membership = freeze_request.membership
        if membership.status != Membership.Status.ACTIVE:
            raise ValidationError('The membership is no longer active.')

        # Apply freeze to membership
        membership.status = Membership.Status.FROZEN
        membership.freeze_start = freeze_request.freeze_start
        membership.freeze_end = freeze_request.freeze_end
        membership.freeze_reason = freeze_request.reason
        membership.save()

        # Mark request as approved
        freeze_request.status = FreezeRequest.Status.APPROVED
        freeze_request.reviewed_by = request.user
        freeze_request.reviewed_at = timezone.now()
        freeze_request.save()

        # Notify the member
        Notification.objects.create(
            recipient=freeze_request.requested_by,
            notification_type=Notification.NotificationType.GENERAL,
            title='Freeze request approved',
            message=(
                f'Your request to freeze "{membership.plan.name}" from '
                f'{freeze_request.freeze_start} to {freeze_request.freeze_end} '
                f'has been approved by {request.user.get_full_name()}.'
            ),
            related_membership_id=membership.id,
        )

        return Response(FreezeRequestListSerializer(freeze_request).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Reject a freeze request."""
        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner/Staff can reject freeze requests.')

        freeze_request = self.get_object()
        if freeze_request.status != FreezeRequest.Status.PENDING:
            raise ValidationError('This request has already been reviewed.')

        rejection_reason = request.data.get('reason', '')

        freeze_request.status = FreezeRequest.Status.REJECTED
        freeze_request.reviewed_by = request.user
        freeze_request.reviewed_at = timezone.now()
        freeze_request.rejection_reason = rejection_reason
        freeze_request.save()

        # Notify the member
        Notification.objects.create(
            recipient=freeze_request.requested_by,
            notification_type=Notification.NotificationType.GENERAL,
            title='Freeze request rejected',
            message=(
                f'Your request to freeze "{freeze_request.membership.plan.name}" '
                f'has been rejected.'
                + (f' Reason: {rejection_reason}' if rejection_reason else '')
            ),
            related_membership_id=freeze_request.membership_id,
        )

        return Response(FreezeRequestListSerializer(freeze_request).data)