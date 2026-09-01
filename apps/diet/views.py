"""
Diet module views.

DietPlanViewSet   — full CRUD + ?q= / ?goal= filtering + /stats action
MealViewSet       — full CRUD for individual meals
MealLogViewSet    — member-scoped daily meal logging
MealLogDailySummaryView — aggregate daily intake vs. plan calorie goal
"""
from datetime import date as date_cls, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaff, IsOwnerOrStaffOrTrainer

from .models import DietPlan, Meal, MealLog
from .serializers import (
    DietPlanSerializer,
    MealSerializer,
    MealLogSerializer,
)

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

DIET_DISCLAIMER = (
    "This diet plan is a general guideline and not medical advice. "
    "Consult a doctor or registered dietitian before making significant "
    "dietary changes, especially if you have a medical condition."
)


def _visible_diet_plans(user):
    """Return the queryset of DietPlan records the requesting user may see."""
    qs = DietPlan.objects.select_related('member', 'created_by').prefetch_related('meals')
    if user.role in ('OWNER', 'STAFF'):
        return qs.all()
    if user.is_member:
        return qs.filter(member=user)
    if user.is_trainer:
        return qs.filter(created_by=user)
    return qs.none()


# ─── ViewSets ─────────────────────────────────────────────────────────────────

class DietPlanViewSet(viewsets.ModelViewSet):
    """
    CRUD for DietPlan records.

    Query parameters
    ----------------
    ?q=<str>     Full-text filter on plan name and member full name.
    ?goal=<str>  Filter by goal code (WEIGHT_LOSS, MUSCLE_GAIN, …).
    """

    serializer_class   = DietPlanSerializer
    permission_classes = [IsAuthenticated]

    # ── Queryset & filtering ──────────────────────────────────────────────────

    def get_queryset(self):
        qs = _visible_diet_plans(self.request.user)

        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(
                member__first_name__icontains=q
            ) | qs.filter(
                member__last_name__icontains=q
            )

        goal = self.request.query_params.get('goal', '').strip().upper()
        if goal:
            qs = qs.filter(goal=goal)

        return qs.order_by('-created_at')

    # ── Permission overrides ──────────────────────────────────────────────────

    def get_permissions(self):
        """
        - List / Retrieve: any authenticated user (queryset already scopes).
        - Create / Update / Destroy: owners, staff, or trainers only.
        """
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    # ── Custom actions ────────────────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='stats', permission_classes=[IsAuthenticated])
    def stats(self, request):
        """
        GET /api/diet/diet-plans/stats/

        Returns aggregate counts scoped to what the current user can see:
            {
                "total":       <int>,
                "active":      <int>,
                "weightLoss":  <int>,
                "muscleGain":  <int>
            }
        """
        qs = _visible_diet_plans(request.user)
        data = {
            'total':      qs.count(),
            'active':     qs.filter(is_active=True).count(),
            'weightLoss': qs.filter(goal=DietPlan.Goal.WEIGHT_LOSS).count(),
            'muscleGain': qs.filter(goal=DietPlan.Goal.MUSCLE_GAIN).count(),
        }
        return Response(data)

    # ── Override retrieve to include disclaimer ───────────────────────────────

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response.data['disclaimer'] = DIET_DISCLAIMER
        return response


class MealViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for Meal records.
    Filter by diet plan: ?diet_plan=<id>
    """

    serializer_class   = MealSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]

    def get_queryset(self):
        qs = Meal.objects.select_related('diet_plan').all()
        diet_plan_id = self.request.query_params.get('diet_plan')
        if diet_plan_id:
            qs = qs.filter(diet_plan_id=diet_plan_id)
        return qs


class MealLogViewSet(viewsets.ModelViewSet):
    """
    CRUD for MealLog (member's actual daily intake).
    Members see only their own logs; owners/staff/trainers may filter by ?member=.
    Optional filter: ?date=YYYY-MM-DD
    """

    serializer_class   = MealLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ('OWNER', 'STAFF'):
            qs = MealLog.objects.all()
        elif user.is_trainer:
            from apps.trainers.models import TrainerMemberAssignment
            assigned = TrainerMemberAssignment.objects.filter(
                trainer=user, is_active=True
            ).values_list('member_id', flat=True)
            qs = MealLog.objects.filter(member_id__in=assigned)
        else:
            qs = MealLog.objects.filter(member=user)

        date_filter = self.request.query_params.get('date')
        if date_filter:
            qs = qs.filter(date=date_filter)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(date__lte=date_to)

        member_id = self.request.query_params.get('member')
        if member_id and user.role in ('OWNER', 'STAFF', 'TRAINER'):
            qs = qs.filter(member_id=member_id)

        return qs.order_by('-date')

    def perform_create(self, serializer):
        serializer.save(member=self.request.user)

    @action(detail=False, methods=['get'], url_path='weekly-summary')
    def weekly_summary(self, request):
        """
        GET /api/diet/meal-logs/weekly-summary/

        Returns daily calorie + macro totals for the last 7 days,
        plus the active plan's targets.
        """
        user = request.user
        member_id = request.query_params.get('member')
        if member_id and user.role in ('OWNER', 'STAFF', 'TRAINER'):
            try:
                member = User.objects.get(pk=member_id, role='MEMBER')
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif user.is_member:
            member = user
        else:
            return Response({'error': 'Specify ?member=<id>.'}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        start = today - timedelta(days=6)

        logs = MealLog.objects.filter(member=member, date__gte=start, date__lte=today)

        daily = {}
        for log in logs:
            d = log.date.isoformat()
            if d not in daily:
                daily[d] = {'calories': 0, 'protein': 0, 'carbs': 0, 'fat': 0}
            daily[d]['calories'] += log.total_calories
            for item in log.food_items:
                daily[d]['protein'] += item.get('protein', 0)
                daily[d]['carbs'] += item.get('carbs', 0)
                daily[d]['fat'] += item.get('fat', 0)

        plan = (
            DietPlan.objects.filter(member=member, is_active=True)
            .order_by('-start_date').first()
        )

        days = []
        for i in range(7):
            d = start + timedelta(days=i)
            key = d.isoformat()
            entry = daily.get(key, {'calories': 0, 'protein': 0, 'carbs': 0, 'fat': 0})
            days.append({
                'date': key,
                'day': d.strftime('%a'),
                'is_today': d == today,
                **entry,
            })

        return Response({
            'days': days,
            'targets': {
                'calories': plan.daily_calories if plan else None,
                'protein': plan.protein_g if plan else None,
                'carbs': plan.carbs_g if plan else None,
                'fat': plan.fats_g if plan else None,
            },
        })


# ─── Daily Summary (function-style view) ─────────────────────────────────────

class MealLogDailySummaryView(APIView):
    """
    GET /api/diet/meal-logs/daily-summary/

    Optional params:
        ?date=YYYY-MM-DD   defaults to today
        ?member=<id>       owner/staff/trainer only; defaults to self for members

    Returns total calories consumed vs. plan goal, macros, and per-log detail.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Resolve target member
        member_id = request.query_params.get('member')
        if member_id and user.role in ('OWNER', 'STAFF', 'TRAINER'):
            try:
                member = User.objects.get(pk=member_id, role='MEMBER')
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if user.role != 'MEMBER':
                return Response(
                    {'error': "Specify ?member=<id> to view a member's summary."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member = user

        # Resolve target date
        date_param = request.query_params.get('date')
        if date_param:
            try:
                target_date = date_cls.fromisoformat(date_param)
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = timezone.localdate()

        logs = MealLog.objects.filter(member=member, date=target_date)

        total_calories = total_protein = total_carbs = total_fat = 0
        log_list = []
        for log in logs:
            total_calories += log.total_calories
            for item in log.food_items:
                total_protein += item.get('protein', 0)
                total_carbs   += item.get('carbs', 0)
                total_fat     += item.get('fat', 0)
            log_list.append({
                'id': log.id, 'date': log.date,
                'food_items': log.food_items,
                'total_calories': log.total_calories,
                'notes': log.notes,
                'created_at': log.created_at,
            })

        active_plan = (
            DietPlan.objects.filter(member=member, is_active=True)
            .order_by('-start_date')
            .first()
        )

        calorie_goal   = active_plan.daily_calories if active_plan else None
        calorie_balance = (total_calories - calorie_goal) if calorie_goal else None
        progress_pct    = (
            round((total_calories / calorie_goal) * 100, 1) if calorie_goal else None
        )

        return Response({
            'member_id':   member.id,
            'member_name': member.get_full_name(),
            'date':        target_date,
            'disclaimer':  DIET_DISCLAIMER,
            'summary': {
                'total_calories_consumed': total_calories,
                'calorie_goal':            calorie_goal,
                'calorie_balance':         calorie_balance,
                'calorie_balance_label': (
                    'on track' if calorie_balance is None
                    else ('deficit' if calorie_balance < 0
                          else ('surplus' if calorie_balance > 0 else 'exact'))
                ),
                'progress_percent': progress_pct,
                'macros': {
                    'protein_g':     total_protein,
                    'carbs_g':       total_carbs,
                    'fat_g':         total_fat,
                    'protein_goal_g': active_plan.protein_g  if active_plan else None,
                    'carbs_goal_g':   active_plan.carbs_g    if active_plan else None,
                    'fat_goal_g':     active_plan.fats_g     if active_plan else None,
                },
            },
            'active_plan': {
                'id': active_plan.id, 'name': active_plan.name, 'goal': active_plan.goal,
            } if active_plan else None,
            'meal_logs': log_list,
        })
