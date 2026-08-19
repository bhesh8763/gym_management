# attendance views
import io
import base64
from datetime import date

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAnyStaffRole, IsOwnerOrStaff
from .models import Attendance, QRAttendanceToken
from .serializers import AttendanceSerializer

User = get_user_model()

# Roles that can record/view attendance for *anyone*.
STAFF_SIDE_ROLES = (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER)

# Import qrcode once at module level; views check QR_AVAILABLE before using it.
try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

_QR_NOT_INSTALLED = {'error': 'qrcode library not installed. Run: pip install qrcode[pil]'}


def _generate_qr_image(data_str):
    """Generate a QR code image and return as base64 string (without data: prefix)."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


class AttendanceViewSet(viewsets.ModelViewSet):
    """
    Owner/Staff/Trainer can record and view attendance for anyone.
    Members can check themselves in/out (create/update their own record only)
    and can only ever see their own attendance history.

    Filter with ?date=YYYY-MM-DD, ?user=<id>, ?type=MEMBER|STAFF|TRAINER
    """
    serializer_class = AttendanceSerializer

    def get_permissions(self):
        # Deleting attendance records stays a staff-side-only action.
        if self.action == 'destroy':
            return [IsAnyStaffRole()]
        return [IsAuthenticated()]

    def get_queryset(self):
        from django.db.models import Prefetch
        from apps.memberships.models import Membership

        active_memberships = Prefetch(
            'user__memberships',
            queryset=Membership.objects.filter(status='ACTIVE').select_related('plan'),
            to_attr='prefetched_active_memberships',
        )
        qs = Attendance.objects.select_related('user', 'marked_by').prefetch_related(active_memberships).all()

        user = self.request.user
        if user.role not in STAFF_SIDE_ROLES:
            # Members (and any other non-staff-side role) only ever see
            # their own attendance — they can't browse everyone else's.
            qs = qs.filter(user=user)

        date_filter = self.request.query_params.get('date')
        user_id = self.request.query_params.get('user')
        att_type = self.request.query_params.get('type')
        if date_filter:
            qs = qs.filter(date=date_filter)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if att_type:
            qs = qs.filter(attendance_type=att_type)
        return qs

    def perform_create(self, serializer):
        requester = self.request.user

        if requester.role not in STAFF_SIDE_ROLES:
            raise PermissionDenied('Only staff-side roles can create attendance records.')

        serializer.save(marked_by=requester)

    def perform_update(self, serializer):
        requester = self.request.user
        instance = self.get_object()

        if requester.role not in STAFF_SIDE_ROLES:
            if instance.user != requester:
                raise PermissionDenied('You can only update your own attendance.')
            # Members may only self-checkout — everything else (status,
            # check_in, attendance_type) stays staff-controlled.
            allowed_fields = {'check_out'}
            attempted_fields = set(serializer.validated_data.keys())
            if attempted_fields - allowed_fields:
                raise PermissionDenied(
                    'Members can only set check_out on their own attendance record.'
                )

        serializer.save()

    @action(detail=False, methods=['post'], url_path='check-in')
    def check_in(self, request):
        """
        POST /api/attendance/records/check-in/
        Member self check-in for today. Creates today's attendance record
        with the current time, unless one already exists.
        """
        user = request.user
        if user.role != User.Role.MEMBER:
            raise PermissionDenied('Only members can self check-in here.')

        today = timezone.localdate()
        now_time = timezone.localtime().time()

        attendance, created = Attendance.objects.get_or_create(
            user=user,
            date=today,
            defaults={
                'attendance_type': Attendance.AttendanceType.MEMBER,
                'status': Attendance.Status.PRESENT,
                'check_in': now_time,
            },
        )
        if not created:
            return Response(
                {'error': 'You are already checked in for today.',
                 'attendance': AttendanceSerializer(attendance).data},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(AttendanceSerializer(attendance).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='check-out')
    def check_out(self, request):
        """
        POST /api/attendance/records/check-out/
        Member self check-out for today's existing attendance record.
        """
        user = request.user
        if user.role != User.Role.MEMBER:
            raise PermissionDenied('Only members can self check-out here.')

        today = timezone.localdate()
        try:
            attendance = Attendance.objects.get(user=user, date=today)
        except Attendance.DoesNotExist:
            return Response(
                {'error': 'You have not checked in today yet.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if attendance.check_out is not None:
            return Response(
                {'error': 'You are already checked out for today.',
                 'attendance': AttendanceSerializer(attendance).data},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attendance.check_out = timezone.localtime().time()
        attendance.save(update_fields=['check_out'])
        return Response(AttendanceSerializer(attendance).data)


class MemberQRCodeView(APIView):
    """
    GET /api/attendance/qr/my/
    Member's own check-in QR — encodes the attendance token.
    Scanning this at the kiosk checks the member in/out.

    GET /api/attendance/qr/<member_id>/   (Owner/Staff only)
    Returns the check-in QR for any specific member.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, member_id=None):
        if not QR_AVAILABLE:
            return Response(_QR_NOT_INSTALLED, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if member_id is not None:
            if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
                raise PermissionDenied('Only Owner or Staff can view other members\' QR codes.')
            try:
                member = User.objects.get(pk=member_id, role=User.Role.MEMBER)
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if request.user.role != User.Role.MEMBER:
                return Response(
                    {'error': 'Only members have QR attendance tokens.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member = request.user

        qr_token = QRAttendanceToken.get_or_create_for_member(member)
        img_base64 = _generate_qr_image(qr_token.token)

        return Response({
            'member_id': member.id,
            'member_name': member.get_full_name(),
            'display_id': member.display_id,
            'token': qr_token.token,
            'qr_image_base64': f'data:image/png;base64,{img_base64}',
        })


class MemberProfileQRView(APIView):
    """
    GET /api/attendance/qr/<member_id>/profile/   (Owner/Staff only)
    Generates a QR code that encodes a public profile URL.
    Scanning this with any phone shows the member's info — no login required.
    The QR content: /member-card.html?id=<member_id>
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):
        if not QR_AVAILABLE:
            return Response(_QR_NOT_INSTALLED, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner or Staff can generate profile QR codes.')

        try:
            member = User.objects.get(pk=member_id, role=User.Role.MEMBER)
        except User.DoesNotExist:
            return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Build the public profile URL — points to the member-card page
        from django.conf import settings as django_settings
        frontend_url = getattr(django_settings, 'FRONTEND_URL', 'http://127.0.0.1:5500')
        profile_url = f"{frontend_url}/member-card.html?id={member.id}"

        img_base64 = _generate_qr_image(profile_url)

        return Response({
            'member_id': member.id,
            'member_name': member.get_full_name(),
            'display_id': member.display_id,
            'profile_url': profile_url,
            'qr_image_base64': f'data:image/png;base64,{img_base64}',
        })


class QRScanCheckInView(APIView):
    """
    POST /api/attendance/qr/scan/
    Body: { "token": "<qr_token>" }

    Open endpoint designed to be called from a tablet/kiosk at the gym
    entrance. No JWT auth required — the QR token IS the authentication.

    Behavior:
    - First scan of the day: creates attendance record with check_in time.
    - Second scan on same day: sets check_out time.
    - Returns the updated attendance record.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_value = request.data.get('token', '').strip()
        if not token_value:
            return Response({'error': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            qr_token = QRAttendanceToken.objects.select_related('member').get(token=token_value)
        except QRAttendanceToken.DoesNotExist:
            return Response({'error': 'Invalid QR token.'}, status=status.HTTP_400_BAD_REQUEST)

        member = qr_token.member
        if not member.is_active:
            return Response({'error': 'Member account is inactive.'}, status=status.HTTP_403_FORBIDDEN)

        today = timezone.localdate()
        now_time = timezone.localtime().time()

        attendance, created = Attendance.objects.get_or_create(
            user=member,
            date=today,
            defaults={
                'attendance_type': Attendance.AttendanceType.MEMBER,
                'status': Attendance.Status.PRESENT,
                'check_in': now_time,
            },
        )

        action_taken = 'checked_in'
        if not created:
            if attendance.check_out is None:
                # Second scan — record check-out
                attendance.check_out = now_time
                attendance.save(update_fields=['check_out'])
                action_taken = 'checked_out'
            else:
                action_taken = 'already_completed'

        return Response({
            'action': action_taken,
            'member_name': member.get_full_name(),
            'display_id': member.display_id,
            'date': today,
            'check_in': attendance.check_in,
            'check_out': attendance.check_out,
            'duration_minutes': attendance.duration_minutes,
        })


class RegenerateQRView(APIView):
    """
    POST /api/attendance/qr/regenerate/  — member regenerates their own QR
    POST /api/attendance/qr/<member_id>/regenerate/  — Owner/Staff regenerates for a member
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, member_id=None):
        if member_id is not None:
            if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
                raise PermissionDenied('Only Owner or Staff can regenerate other members\' QR codes.')
            try:
                member = User.objects.get(pk=member_id, role=User.Role.MEMBER)
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if request.user.role != User.Role.MEMBER:
                return Response({'error': 'Only members can use this endpoint.'}, status=status.HTTP_400_BAD_REQUEST)
            member = request.user

        qr_token = QRAttendanceToken.get_or_create_for_member(member)
        qr_token.regenerate()

        return Response({
            'message': 'QR token regenerated successfully.',
            'member_name': member.get_full_name(),
            'new_token': qr_token.token,
        })


class SharedCheckinQRView(APIView):
    """
    GET /api/attendance/checkin-qr/
    Owner or Staff only. Returns a QR code image that encodes the shared
    check-in page URL (checkin.html). Print or display this at the gym
    entrance — any member scans it, opens the page, logs in, and is
    checked in automatically.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not QR_AVAILABLE:
            return Response(_QR_NOT_INSTALLED, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if request.user.role not in (User.Role.OWNER, User.Role.STAFF):
            raise PermissionDenied('Only Owner or Staff can generate the shared check-in QR.')

        from django.conf import settings as django_settings
        frontend_url = getattr(django_settings, 'FRONTEND_URL', 'http://127.0.0.1:5500')
        checkin_url = f"{frontend_url}/checkin.html"

        img_base64 = _generate_qr_image(checkin_url)

        return Response({
            'checkin_url': checkin_url,
            'qr_image_base64': f'data:image/png;base64,{img_base64}',
        })


class PublicMemberProfileView(APIView):
    """
    GET /api/attendance/member-profile/<member_id>/
    Public endpoint — no authentication required.
    Returns member info to display when someone scans the profile QR code.
    Only returns non-sensitive fields (name, display_id, membership status, photo).
    """
    permission_classes = [AllowAny]

    def get(self, request, member_id):
        try:
            member = User.objects.get(pk=member_id, role=User.Role.MEMBER, is_active=True)
        except User.DoesNotExist:
            return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Get active membership
        active_membership = member.memberships.filter(
            status='ACTIVE'
        ).select_related('plan').order_by('-start_date').first()

        # Get member profile
        profile = None
        try:
            profile = member.member_profile
        except Exception:
            pass

        # Build profile picture URL
        pic_url = None
        if member.profile_picture:
            try:
                pic_url = request.build_absolute_uri(member.profile_picture.url)
            except Exception:
                pass

        return Response({
            'id': member.id,
            'display_id': member.display_id,
            'full_name': member.get_full_name(),
            'profile_picture': pic_url,
            'membership': {
                'plan_name': active_membership.plan.name,
                'status': active_membership.status,
                'end_date': str(active_membership.end_date),
            } if active_membership else None,
            'fitness_goal': profile.fitness_goal_display if profile and hasattr(profile, 'fitness_goal_display') else None,
            'fitness_level': profile.fitness_level_display if profile and hasattr(profile, 'fitness_level_display') else None,
            'joined': str(member.date_joined.date()),
        })