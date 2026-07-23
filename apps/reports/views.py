"""
Reports & Analytics — read-only aggregation views.

These endpoints don't own any models of their own; they query across the
existing apps (payments, memberships, attendance, equipment, lockers,
members, staff) and return summarized data for dashboards/charts.

All endpoints are Owner/Staff only.
"""
from datetime import timedelta

from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.permissions import IsOwnerOrStaff
from apps.payments.models import Payment
from apps.memberships.models import Membership, MembershipPlan
from apps.attendance.models import Attendance
from apps.equipment.models import Equipment, MaintenanceRecord
from apps.lockers.models import Locker, LockerAssignment
from apps.members.models import MemberProfile
from apps.staff.models import StaffProfile, LeaveRequest


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def revenue_report(request):
    """
    GET /api/reports/revenue/
    Monthly revenue trend (last 12 months), breakdown by payment method,
    breakdown by payment status, and breakdown by what the payment was for.
    """
    today = timezone.now().date()
    twelve_months_ago = (today.replace(day=1) - timedelta(days=365))

    monthly = (
        Payment.objects.filter(status=Payment.PaymentStatus.PAID, created_at__date__gte=twelve_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('amount_paid'), count=Count('id'))
        .order_by('month')
    )

    by_method = (
        Payment.objects.filter(status=Payment.PaymentStatus.PAID)
        .values('payment_method')
        .annotate(total=Sum('amount_paid'), count=Count('id'))
        .order_by('-total')
    )

    by_status = (
        Payment.objects.values('status')
        .annotate(total=Sum('amount_paid'), count=Count('id'))
        .order_by('-total')
    )

    by_purpose = (
        Payment.objects.filter(status=Payment.PaymentStatus.PAID)
        .values('payment_for')
        .annotate(total=Sum('amount_paid'), count=Count('id'))
        .order_by('-total')
    )

    totals = Payment.objects.aggregate(
        collected=Sum('amount_paid', filter=Q(status=Payment.PaymentStatus.PAID)),
        pending=Sum('amount_paid', filter=Q(status=Payment.PaymentStatus.PENDING)),
        refunded=Sum('amount_paid', filter=Q(status=Payment.PaymentStatus.REFUNDED)),
    )

    return Response({
        'monthly_trend': [
            {'month': row['month'].strftime('%Y-%m'), 'total': row['total'] or 0, 'count': row['count']}
            for row in monthly
        ],
        'by_method': list(by_method),
        'by_status': list(by_status),
        'by_purpose': list(by_purpose),
        'totals': {
            'collected': totals['collected'] or 0,
            'pending': totals['pending'] or 0,
            'refunded': totals['refunded'] or 0,
        },
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def membership_report(request):
    """
    GET /api/reports/memberships/
    Status breakdown, plan popularity, and memberships expiring in the
    next 30 days (useful for renewal follow-ups).
    """
    today = timezone.now().date()

    by_status = (
        Membership.objects.values('status')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    by_plan = (
        Membership.objects.values('plan__name')
        .annotate(count=Count('id'), revenue=Sum('price_paid'))
        .order_by('-count')
    )

    expiring_soon = (
        Membership.objects.filter(
            status=Membership.Status.ACTIVE,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=30),
        )
        .select_related('member', 'plan')
        .order_by('end_date')
    )

    return Response({
        'by_status': list(by_status),
        'by_plan': [
            {'plan': row['plan__name'], 'count': row['count'], 'revenue': row['revenue'] or 0}
            for row in by_plan
        ],
        'total_active': Membership.objects.filter(status=Membership.Status.ACTIVE).count(),
        'total_members': MemberProfile.objects.count(),
        'expiring_soon': [
            {
                'id': m.id,
                'member_name': m.member.get_full_name(),
                'plan_name': m.plan.name,
                'end_date': m.end_date,
            }
            for m in expiring_soon[:25]
        ],
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def attendance_report(request):
    """
    GET /api/reports/attendance/
    Daily check-in counts for the last 30 days, plus a breakdown by
    attendance type (member/staff/trainer).
    """
    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=29)

    daily = (
        Attendance.objects.filter(date__gte=thirty_days_ago)
        .values('date')
        .annotate(count=Count('id'))
        .order_by('date')
    )

    by_type = (
        Attendance.objects.filter(date__gte=thirty_days_ago)
        .values('attendance_type')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    return Response({
        'daily': [{'date': row['date'], 'count': row['count']} for row in daily],
        'by_type': list(by_type),
        'total_last_30_days': Attendance.objects.filter(date__gte=thirty_days_ago).count(),
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def equipment_report(request):
    """
    GET /api/reports/equipment/
    Condition breakdown, maintenance cost total, and upcoming/overdue
    maintenance counts.
    """
    today = timezone.now().date()

    by_condition = (
        Equipment.objects.values('condition')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    maintenance_cost = MaintenanceRecord.objects.aggregate(total=Sum('cost'))['total'] or 0

    upcoming = MaintenanceRecord.objects.filter(
        status=MaintenanceRecord.MaintenanceStatus.SCHEDULED,
        scheduled_date__gte=today,
    ).count()

    overdue = MaintenanceRecord.objects.filter(
        status=MaintenanceRecord.MaintenanceStatus.SCHEDULED,
        scheduled_date__lt=today,
    ).count()

    return Response({
        'by_condition': list(by_condition),
        'total_items': Equipment.objects.aggregate(total=Sum('quantity'))['total'] or 0,
        'maintenance_cost_total': maintenance_cost,
        'upcoming_maintenance': upcoming,
        'overdue_maintenance': overdue,
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def locker_report(request):
    """
    GET /api/reports/lockers/
    Occupancy breakdown and monthly recurring revenue from locker fees.
    """
    by_status = (
        Locker.objects.values('status')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    total = Locker.objects.count()
    occupied = Locker.objects.filter(status=Locker.LockerStatus.OCCUPIED).count()

    mrr = (
        LockerAssignment.objects.filter(is_active=True)
        .select_related('locker')
        .aggregate(total=Sum('locker__monthly_fee'))['total'] or 0
    )

    return Response({
        'by_status': list(by_status),
        'total_lockers': total,
        'occupied': occupied,
        'occupancy_rate': round((occupied / total * 100), 1) if total else 0,
        'monthly_recurring_revenue': mrr,
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def staff_report(request):
    """
    GET /api/reports/staff/
    Headcount by department and pending leave request count.
    """
    by_department = (
        StaffProfile.objects.values('department')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    return Response({
        'by_department': list(by_department),
        'total_staff': StaffProfile.objects.count(),
        'pending_leave_requests': LeaveRequest.objects.filter(
            status=LeaveRequest.LeaveStatus.PENDING
        ).count(),
    })


@api_view(['GET'])
@permission_classes([IsOwnerOrStaff])
def overview_report(request):
    """
    GET /api/reports/overview/
    Top-line KPIs for a landing dashboard: revenue this month, active
    members, occupancy, and equipment condition — one call per page load.
    """
    today = timezone.now().date()
    month_start = today.replace(day=1)

    revenue_this_month = Payment.objects.filter(
        status=Payment.PaymentStatus.PAID, created_at__date__gte=month_start,
    ).aggregate(total=Sum('amount_paid'))['total'] or 0

    return Response({
        'revenue_this_month': revenue_this_month,
        'active_memberships': Membership.objects.filter(status=Membership.Status.ACTIVE).count(),
        'total_members': MemberProfile.objects.count(),
        'total_staff': StaffProfile.objects.count(),
        'lockers_occupied': Locker.objects.filter(status=Locker.LockerStatus.OCCUPIED).count(),
        'lockers_total': Locker.objects.count(),
        'equipment_out_of_service': Equipment.objects.filter(
            condition=Equipment.Condition.OUT_OF_SERVICE
        ).count(),
        'attendance_today': Attendance.objects.filter(date=today).count(),
    })
