"""
Diet module views.

DietPlanViewSet         — full CRUD + ?q= / ?goal= filtering + /stats action
MealViewSet             — full CRUD for individual meals
MealLogViewSet          — member-scoped daily meal logging
MealLogDailySummaryView — aggregate daily intake vs. plan calorie goal
EffectiveDietPlanView   — personal plan if assigned, else a general goal-based plan
MealChecklistViewSet    — daily meal-completion checklist + history
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
from apps.gyms.tenancy import branch_queryset, gym_users, tenant_queryset
from apps.gyms.models import GymMembership

from .models import DietPlan, Meal, MealLog, MealChecklist
from .serializers import (
    DietPlanSerializer,
    MealSerializer,
    MealLogSerializer,
    MealChecklistSerializer,
)

User = get_user_model()


# ─── Helpers ──────────────────────────────────────────────────────────────────

DIET_DISCLAIMER = (
    "This diet plan is a general guideline and not medical advice. "
    "Consult a doctor or registered dietitian before making significant "
    "dietary changes, especially if you have a medical condition."
)

# ─── General (non-personal) diet plans, keyed on DietPlan.Goal ────────────────
# Used only as a fallback when a member has no trainer-assigned DietPlan.
# These are NOT stored as DietPlan/Meal rows — they're static templates.
# Every one of DietPlan.Goal's 5 values has a template here, each with at
# least 4 meals, so the checklist is never empty regardless of which goal
# a member ends up mapped to.

GENERAL_MEAL_PLANS = {
    'MUSCLE_GAIN': [
        {'meal_type': 'BREAKFAST',    'food_name': '2 eggs + oats + banana'},
        {'meal_type': 'MID_MORNING',  'food_name': 'Milk + nuts'},
        {'meal_type': 'LUNCH',        'food_name': 'Rice + chicken/paneer + vegetables'},
        {'meal_type': 'PRE_WORKOUT',  'food_name': 'Banana + peanut butter'},
        {'meal_type': 'POST_WORKOUT', 'food_name': 'Protein-rich meal or shake'},
        {'meal_type': 'DINNER',       'food_name': 'Rice/roti + protein + vegetables'},
    ],
    'WEIGHT_LOSS': [
        {'meal_type': 'BREAKFAST',      'food_name': 'Eggs + vegetables/oats'},
        {'meal_type': 'MID_MORNING',    'food_name': 'Fruit'},
        {'meal_type': 'LUNCH',          'food_name': 'Rice/roti + lean protein + vegetables'},
        {'meal_type': 'EVENING_SNACK',  'food_name': 'Light healthy snack'},
        {'meal_type': 'DINNER',         'food_name': 'Protein + vegetables'},
    ],
    'RECOMPOSITION': [
        {'meal_type': 'BREAKFAST',    'food_name': 'Eggs + oats + berries'},
        {'meal_type': 'MID_MORNING',  'food_name': 'Greek yogurt or protein shake + nuts'},
        {'meal_type': 'LUNCH',        'food_name': 'Rice/roti + lean protein + vegetables'},
        {'meal_type': 'PRE_WORKOUT',  'food_name': 'Banana + small handful of nuts'},
        {'meal_type': 'POST_WORKOUT', 'food_name': 'Protein-rich meal or shake'},
        {'meal_type': 'DINNER',       'food_name': 'Lean protein + vegetables, moderate carbs'},
    ],
    'MAINTENANCE': [
        {'meal_type': 'BREAKFAST',     'food_name': 'Eggs/oats + fruit'},
        {'meal_type': 'LUNCH',         'food_name': 'Rice/roti + protein + vegetables'},
        {'meal_type': 'EVENING_SNACK', 'food_name': 'Fruit or light snack'},
        {'meal_type': 'DINNER',        'food_name': 'Roti/rice + protein + vegetables'},
    ],
    'ENDURANCE': [
        {'meal_type': 'BREAKFAST',    'food_name': 'Oats + banana + honey'},
        {'meal_type': 'MID_MORNING',  'food_name': 'Fruit + a handful of nuts'},
        {'meal_type': 'LUNCH',        'food_name': 'Rice/roti + protein + vegetables'},
        {'meal_type': 'PRE_WORKOUT',  'food_name': 'Toast + banana or energy bar'},
        {'meal_type': 'POST_WORKOUT', 'food_name': 'Carb + protein recovery meal'},
        {'meal_type': 'DINNER',       'food_name': 'Roti/rice + protein + vegetables'},
    ],
}

# Maps MemberProfile.fitness_goal (WEIGHT_LOSS, MUSCLE_GAIN, ENDURANCE,
# FLEXIBILITY, GENERAL, REHAB) to the nearest DietPlan.Goal used above.
# Anything blank, unrecognized, or without a direct match falls back to
# MAINTENANCE, so a template is always found — the checklist is never empty.
FITNESS_GOAL_TO_DIET_GOAL = {
    'WEIGHT_LOSS': 'WEIGHT_LOSS',
    'MUSCLE_GAIN': 'MUSCLE_GAIN',
    'ENDURANCE':   'ENDURANCE',
    'FLEXIBILITY': 'MAINTENANCE',
    'GENERAL':     'MAINTENANCE',
    'REHAB':       'MAINTENANCE',
}

GOAL_LABELS = {
    'WEIGHT_LOSS':   'Weight Loss',
    'MUSCLE_GAIN':   'Muscle Gain',
    'RECOMPOSITION': 'Recomposition',
    'MAINTENANCE':   'Maintenance',
    'ENDURANCE':     'Endurance',
}


def _general_plan_for(member):
    """Build a read-only, non-persisted 'general plan' payload for a member
    with no trainer-assigned DietPlan, based on their MemberProfile.fitness_goal,
    mapped onto DietPlan.Goal's 5 categories (defaulting to MAINTENANCE)."""
    profile = getattr(member, 'member_profile', None)
    fitness_goal = (getattr(profile, 'fitness_goal', '') or '').upper()
    goal = FITNESS_GOAL_TO_DIET_GOAL.get(fitness_goal, 'MAINTENANCE')
    template = GENERAL_MEAL_PLANS[goal]
    meal_type_labels = dict(Meal.MealType.choices)
    meals = [
        {
            'id': None,
            'meal_type': m['meal_type'],
            'meal_type_display': meal_type_labels.get(m['meal_type'], m['meal_type']),
            'food_name': m['food_name'],
            'portion': '', 'calories': None, 'time_suggestion': None, 'notes': '',
        }
        for m in template
    ]
    return {
        'id': None,
        'source': 'GENERAL',
        'name': f'General Plan — {GOAL_LABELS[goal]}',
        'goal': goal,
        'goal_display': GOAL_LABELS[goal],
        'daily_calories': None, 'protein_g': None, 'carbs_g': None, 'fats_g': None,
        'is_active': True, 'status': 'Active',
        'meals': meals,
        'disclaimer': DIET_DISCLAIMER,
    }


def _visible_diet_plans(user, request=None):
    """Return the queryset of DietPlan records the requesting user may see."""
    qs = DietPlan.objects.select_related('member', 'created_by').prefetch_related('meals')
    role = getattr(request, 'gym_role', user.role) if request is not None else user.role
    if role in (User.Role.OWNER, User.Role.STAFF):
        qs = qs.all()
    elif role == User.Role.MEMBER:
        qs = qs.filter(member=user)
    elif role == User.Role.TRAINER:
        qs = qs.filter(created_by=user)
    else:
        qs = qs.none()
    return tenant_queryset(qs, request) if request is not None else qs


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
        qs = _visible_diet_plans(self.request.user, self.request)

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

    def perform_create(self, serializer):
        serializer.save(
            gym=getattr(self.request, 'gym', None),
            branch=getattr(self.request, 'branch', None),
        )

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
        qs = _visible_diet_plans(request.user, request)
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
        qs = Meal.objects.select_related('diet_plan').filter(
            diet_plan__gym=getattr(self.request, 'gym', None),
        )
        qs = branch_queryset(qs, self.request, field='diet_plan__branch')
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
        if getattr(self.request, 'gym_role', user.role) in (User.Role.OWNER, User.Role.STAFF):
            qs = MealLog.objects.all()
        elif getattr(self.request, 'gym_role', user.role) == User.Role.TRAINER:
            from apps.trainers.models import TrainerMemberAssignment
            assigned = TrainerMemberAssignment.objects.filter(
                trainer=user, is_active=True
            ).values_list('member_id', flat=True)
            qs = MealLog.objects.filter(member_id__in=assigned)
        else:
            qs = MealLog.objects.filter(member=user)
        qs = tenant_queryset(qs, self.request)

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
        if member_id and getattr(self.request, 'gym_role', user.role) in (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER):
            qs = qs.filter(member_id=member_id)

        return qs.order_by('-date')

    def perform_create(self, serializer):
        serializer.save(
            member=self.request.user,
            gym=getattr(self.request, 'gym', None),
            branch=getattr(self.request, 'branch', None),
        )

    @action(detail=False, methods=['get'], url_path='weekly-summary')
    def weekly_summary(self, request):
        """
        GET /api/diet/meal-logs/weekly-summary/

        Returns daily calorie + macro totals for the last 7 days,
        plus the active plan's targets.
        """
        user = request.user
        member_id = request.query_params.get('member')
        if member_id and getattr(request, 'gym_role', user.role) in ('OWNER', 'STAFF', 'TRAINER'):
            try:
                member = gym_users(
                    gym=getattr(request, 'gym', None),
                    role=GymMembership.Role.MEMBER,
                ).get(pk=member_id)
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        elif getattr(request, 'gym_role', user.role) == User.Role.MEMBER:
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
        if member_id and getattr(request, 'gym_role', user.role) in ('OWNER', 'STAFF', 'TRAINER'):
            try:
                member = gym_users(
                    gym=getattr(request, 'gym', None),
                    role=GymMembership.Role.MEMBER,
                ).get(pk=member_id)
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if getattr(request, 'gym_role', user.role) != 'MEMBER':
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


# ─── Effective Plan (personal-first, general fallback) ───────────────────────

class EffectiveDietPlanView(APIView):
    """
    GET /api/diet/effective-plan/?member=<id>

    Returns the ONE plan a member should see today:
      - their active trainer-assigned DietPlan if one exists (source=PERSONAL)
      - otherwise a general plan built from MemberProfile.fitness_goal (source=GENERAL)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        member_id = request.query_params.get('member')
        if member_id and user.role in ('OWNER', 'STAFF', 'TRAINER'):
            try:
                member = User.objects.get(pk=member_id, role='MEMBER')
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not user.is_member:
                return Response(
                    {'error': "Specify ?member=<id> to view a member's effective plan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member = user

        personal_plan = (
            DietPlan.objects.filter(member=member, is_active=True)
            .prefetch_related('meals')
            .order_by('-start_date')
            .first()
        )
        if personal_plan:
            data = DietPlanSerializer(personal_plan, context={'request': request}).data
            data['source'] = 'PERSONAL'
            data['disclaimer'] = DIET_DISCLAIMER
            return Response(data)

        return Response(_general_plan_for(member))


# ─── Daily Meal Checklist ─────────────────────────────────────────────────────

class MealChecklistViewSet(viewsets.ModelViewSet):
    """
    CRUD + history for a member's daily meal checklist.
    Members see only their own; owners/staff/trainers may filter by ?member=.
    """

    serializer_class   = MealChecklistSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in (User.Role.OWNER, User.Role.STAFF):
            qs = MealChecklist.objects.all()
        elif user.is_trainer:
            from apps.trainers.models import TrainerMemberAssignment
            assigned = TrainerMemberAssignment.objects.filter(
                trainer=user, is_active=True
            ).values_list('member_id', flat=True)
            qs = MealChecklist.objects.filter(member_id__in=assigned)
        else:
            qs = MealChecklist.objects.filter(member=user)

        member_id = self.request.query_params.get('member')
        if member_id and user.role in (User.Role.OWNER, User.Role.STAFF, User.Role.TRAINER):
            qs = qs.filter(member_id=member_id)

        date_filter = self.request.query_params.get('date')
        if date_filter:
            qs = qs.filter(date=date_filter)

        return qs.order_by('-date')

    def perform_create(self, serializer):
        serializer.save(member=self.request.user)

    @action(detail=False, methods=['get', 'post'], url_path='today', permission_classes=[IsAuthenticated])
    def today(self, request):
        """
        GET  /api/diet/meal-checklist/today/
             -> today's checklist for the current member (or a default empty shape).
        POST /api/diet/meal-checklist/today/
             body: {"completed_meal_types": ["BREAKFAST", "LUNCH"], "total_meals": 5}
             -> creates/updates today's record for the current member only.
        """
        if not request.user.is_member:
            return Response({'error': 'Only members have a personal checklist.'},
                             status=status.HTTP_400_BAD_REQUEST)

        today_str = timezone.localdate().isoformat()

        if request.method == 'GET':
            obj = MealChecklist.objects.filter(member=request.user, date=today_str).first()
            if not obj:
                return Response({
                    'date': today_str, 'completed_meal_types': [],
                    'total_meals': 0, 'completed_count': 0, 'progress_percent': 0,
                })
            return Response(MealChecklistSerializer(obj).data)

        completed = request.data.get('completed_meal_types', [])
        if not isinstance(completed, list):
            return Response({'error': 'completed_meal_types must be a list.'},
                             status=status.HTTP_400_BAD_REQUEST)
        try:
            total = int(request.data.get('total_meals', 0))
        except (TypeError, ValueError):
            total = 0

        obj, _created = MealChecklist.objects.update_or_create(
            member=request.user, date=today_str,
            defaults={'completed_meal_types': completed, 'total_meals': total},
        )
        return Response(MealChecklistSerializer(obj).data)