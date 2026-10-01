"""
Business logic for attendance operations.
"""
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.gyms.models import GymMembership
from apps.memberships.models import Membership

from .models import Attendance, QRAttendanceToken


class ScanResult:
    """Result of a QR scan operation."""
    def __init__(self, success: bool, action: str, code: str, message: str, time, member_data: dict):
        self.success = success
        self.action = action
        self.code = code
        self.message = message
        self.time = time
        self.member_data = member_data


def _get_member_data(member, request=None):
    """Build member data dict for scan response."""
    from apps.members.models import MemberProfile

    # Latest plan membership regardless of status, so denied scans still show
    # which plan is expired or frozen.
    plan_membership = member.memberships.filter(
        status__in=[
            Membership.Status.ACTIVE,
            Membership.Status.EXPIRED,
            Membership.Status.FROZEN,
        ],
    ).select_related('plan').order_by('-end_date').first()

    profile_picture = None
    if member.profile_picture:
        try:
            if request:
                profile_picture = request.build_absolute_uri(member.profile_picture.url)
            else:
                profile_picture = member.profile_picture.url
        except (ValueError, AttributeError):
            pass

    days_left = None
    if plan_membership:
        if plan_membership.status == Membership.Status.EXPIRED:
            days_left = 0
        elif plan_membership.end_date:
            delta = plan_membership.end_date - timezone.now().date()
            days_left = max(0, delta.days)

    return {
        'name': member.get_full_name(),
        'member_id': member.id,
        'profile_picture': profile_picture,
        'plan_name': plan_membership.plan.name if plan_membership else None,
        'end_date': str(plan_membership.end_date) if plan_membership else None,
        'days_left': days_left,
    }


def _check_cooldown(attendance: Attendance, now_time) -> bool:
    """Check if attendance record was modified within last 60 seconds."""
    if attendance.created_at:
        elapsed = timezone.now() - attendance.created_at
        if elapsed < timedelta(seconds=60):
            return True
    return False


def scan_qr(token_value: str, request=None) -> ScanResult:
    """
    Process a QR scan for attendance check-in/out.

    Args:
        token_value: The QR token string.
        request: Optional request object for building absolute URLs.

    Returns:
        ScanResult with success, action, code, message, time, member_data.

    Codes:
        INVALID_TOKEN - token not found, missing, or not linked to a gym
        INACTIVE - user or member account inactive
        NO_MEMBERSHIP - no active gym membership
        EXPIRED - membership expired (message includes expiry date)
        FROZEN - membership frozen
        COOLDOWN - scanned too recently (within 60s)
        CHECK_IN - successful check-in
        CHECK_OUT - successful check-out
        ALREADY_COMPLETED - already checked in and out today
    """
    token_value = (token_value or '').strip()
    if not token_value:
        return ScanResult(
            success=False, action='', code='INVALID_TOKEN',
            message='Token is required.', time=None, member_data={}
        )

    try:
        qr_token = QRAttendanceToken.objects.select_related(
            'member', 'gym', 'branch'
        ).get(token=token_value)
    except QRAttendanceToken.DoesNotExist:
        return ScanResult(
            success=False, action='', code='INVALID_TOKEN',
            message='Invalid QR token.', time=None, member_data={}
        )

    member = qr_token.member

    # User active check
    if not member.is_active:
        return ScanResult(
            success=False, action='', code='INACTIVE',
            message='Member account is inactive.', time=None,
            member_data=_get_member_data(member, request)
        )

    # Gym linkage check — deny before any membership validation or
    # attendance write when the token is not bound to a gym.
    if not qr_token.gym_id:
        return ScanResult(
            success=False, action='', code='INVALID_TOKEN',
            message='QR code is not linked to a gym.', time=None,
            member_data=_get_member_data(member, request)
        )

    # Gym membership checks (role-based access to gym)
    gym = qr_token.gym
    if gym.status not in (gym.Status.ACTIVE, gym.Status.TRIAL):
        return ScanResult(
            success=False, action='', code='NO_MEMBERSHIP',
            message='Gym is not active.', time=None,
            member_data=_get_member_data(member, request)
        )

    # Get the gym membership (role check)
    gym_membership = GymMembership.objects.filter(
        gym=gym, user=member, role=GymMembership.Role.MEMBER
    ).first()

    if not gym_membership:
        return ScanResult(
            success=False, action='', code='NO_MEMBERSHIP',
            message='No active membership in this gym.', time=None,
            member_data=_get_member_data(member, request)
        )

    if gym_membership.status != GymMembership.Status.ACTIVE:
        return ScanResult(
            success=False, action='', code='NO_MEMBERSHIP',
            message='Membership is not active.', time=None,
            member_data=_get_member_data(member, request)
        )

    # Check Membership (plan, expiration, freeze) from apps.memberships
    membership = Membership.objects.filter(
        member=member, gym=gym, status__in=[Membership.Status.ACTIVE, Membership.Status.EXPIRED, Membership.Status.FROZEN]
    ).select_related('plan').order_by('-end_date').first()

    if not membership:
        return ScanResult(
            success=False, action='', code='NO_MEMBERSHIP',
            message='No membership plan found.', time=None,
            member_data=_get_member_data(member, request)
        )

    today_date = timezone.now().date()
    if membership.status == Membership.Status.EXPIRED or (membership.end_date and membership.end_date < today_date):
        return ScanResult(
            success=False, action='', code='EXPIRED',
            message=f'Membership expired on {membership.end_date}.',
            time=None, member_data=_get_member_data(member, request)
        )
    if membership.status == Membership.Status.FROZEN:
        return ScanResult(
            success=False, action='', code='FROZEN',
            message='Membership is frozen.', time=None,
            member_data=_get_member_data(member, request)
        )
    if membership.status != Membership.Status.ACTIVE:
        return ScanResult(
            success=False, action='', code='NO_MEMBERSHIP',
            message='Membership is not active.', time=None,
            member_data=_get_member_data(member, request)
        )

    # Branch check
    if qr_token.branch_id:
        branch_active = GymMembership.objects.filter(
            gym=gym, user=member,
            branch_memberships__branch=qr_token.branch,
            status=GymMembership.Status.ACTIVE,
        ).exists()
        if not branch_active:
            return ScanResult(
                success=False, action='', code='NO_MEMBERSHIP',
                message='Member not active in this branch.', time=None,
                member_data=_get_member_data(member, request)
            )

    today = timezone.localdate()
    now = timezone.localtime()
    now_time = now.time()

    with transaction.atomic():
        attendance, created = Attendance.objects.select_for_update().get_or_create(
            gym=qr_token.gym,
            branch=qr_token.branch,
            user=member,
            date=today,
            defaults={
                'attendance_type': Attendance.AttendanceType.MEMBER,
                'status': Attendance.Status.PRESENT,
                'check_in': now_time,
                'source': Attendance.Source.QR,
            },
        )

        if not created:
            # Check cooldown
            if _check_cooldown(attendance, now_time):
                return ScanResult(
                    success=False, action='', code='COOLDOWN',
                    message='Scanned too recently. Please wait.',
                    time=attendance.check_in or now_time,
                    member_data=_get_member_data(member, request)
                )

            if attendance.check_out is None:
                # Second scan - check out
                attendance.check_out = now_time
                attendance.source = Attendance.Source.QR
                attendance.save(update_fields=['check_out', 'source'])
                return ScanResult(
                    success=True, action='CHECK_OUT', code='CHECK_OUT',
                    message='Checked out successfully.',
                    time=now_time, member_data=_get_member_data(member, request)
                )
            else:
                # Already completed
                return ScanResult(
                    success=False, action='', code='ALREADY_COMPLETED',
                    message='Attendance already completed for today.',
                    time=attendance.check_out,
                    member_data=_get_member_data(member, request)
                )
        else:
            # First scan - check in
            return ScanResult(
                success=True, action='CHECK_IN', code='CHECK_IN',
                message='Checked in successfully.',
                time=now_time, member_data=_get_member_data(member, request)
            )