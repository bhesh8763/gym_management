# diet views
from datetime import date as date_type

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaffOrTrainer

from .models import DietPlan, Meal, MealLog
from .serializers import DietPlanSerializer, MealSerializer, MealLogSerializer

DIET_DISCLAIMER = (
    "This diet plan is a general guideline and not medical advice. "
    "Consult a doctor or registered dietitian before making significant "
    "dietary changes, especially if you have a medical condition."
)


def _visible_diet_plans(user):
    if user.role in ['OWNER', 'STAFF']:
        return DietPlan.objects.all()
    if user.is_member:
        return DietPlan.objects.filter(member=user)
    if user.is_trainer:
        return DietPlan.objects.filter(trainer=user)
    return DietPlan.objects.none()


class DietPlanListCreateView(generics.ListCreateAPIView):
    serializer_class = DietPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return _visible_diet_plans(self.request.user)


class DietPlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DietPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_diet_plans(self.request.user)

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        response.data['disclaimer'] = DIET_DISCLAIMER
        return response


class MealListCreateView(generics.ListCreateAPIView):
    queryset = Meal.objects.all()
    serializer_class = MealSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


class MealDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Meal.objects.all()
    serializer_class = MealSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


def _visible_meal_logs(user):
    if user.role in ['OWNER', 'STAFF']:
        return MealLog.objects.all()
    if user.is_member:
        return MealLog.objects.filter(member=user)
    if user.is_trainer:
        from apps.trainers.models import TrainerMemberAssignment
        assigned_ids = TrainerMemberAssignment.objects.filter(
            trainer=user, is_active=True
        ).values_list('member_id', flat=True)
        return MealLog.objects.filter(member_id__in=assigned_ids)
    return MealLog.objects.none()


class MealLogListCreateView(generics.ListCreateAPIView):
    serializer_class = MealLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = _visible_meal_logs(self.request.user)
        # Optional filter by date: ?date=YYYY-MM-DD
        date_filter = self.request.query_params.get('date')
        if date_filter:
            qs = qs.filter(date=date_filter)
        # Optional filter by member: ?member=<id>  (staff/owner only)
        member_id = self.request.query_params.get('member')
        if member_id and self.request.user.role in ['OWNER', 'STAFF', 'TRAINER']:
            qs = qs.filter(member_id=member_id)
        return qs


class MealLogDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MealLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_meal_logs(self.request.user)


class MealLogDailySummaryView(APIView):
    """
    GET /api/diet/meal-logs/daily-summary/
    Optional query params:
      ?date=YYYY-MM-DD   — defaults to today
      ?member=<id>       — Owner/Staff/Trainer only; defaults to self for members

    Returns:
    - All meal log entries for the day
    - Total calories consumed
    - Calorie goal from the member's active diet plan (if any)
    - Deficit or surplus
    - Macro totals (protein, carbs, fat) summed from food_items
    - Progress percentage toward calorie goal
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Determine which member we're reporting on
        member_id = request.query_params.get('member')
        if member_id and user.role in ['OWNER', 'STAFF', 'TRAINER']:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                member = User.objects.get(pk=member_id, role='MEMBER')
            except User.DoesNotExist:
                return Response({'error': 'Member not found.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            if user.role != 'MEMBER':
                return Response(
                    {'error': 'Specify ?member=<id> to view a member\'s summary.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            member = user

        # Resolve date
        date_param = request.query_params.get('date')
        if date_param:
            try:
                from datetime import date as date_cls
                target_date = date_cls.fromisoformat(date_param)
            except ValueError:
                return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = timezone.localdate()

        # Fetch all meal logs for this member on the target date
        logs = MealLog.objects.filter(member=member, date=target_date)

        # Aggregate totals
        total_calories = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0

        log_list = []
        for log in logs:
            total_calories += log.total_calories
            for item in log.food_items:
                total_protein += item.get('protein', 0)
                total_carbs += item.get('carbs', 0)
                total_fat += item.get('fat', 0)
            log_list.append({
                'id': log.id,
                'date': log.date,
                'food_items': log.food_items,
                'total_calories': log.total_calories,
                'notes': log.notes,
                'created_at': log.created_at,
            })

        # Get calorie goal from active diet plan
        active_plan = DietPlan.objects.filter(
            member=member,
            is_active=True,
        ).order_by('-start_date').first()

        calorie_goal = active_plan.daily_calories if active_plan else None
        protein_goal = active_plan.protein_grams if active_plan else None
        carbs_goal = active_plan.carbs_grams if active_plan else None
        fat_goal = active_plan.fat_grams if active_plan else None

        # Calculate deficit/surplus and progress
        calorie_balance = None
        progress_percent = None
        if calorie_goal:
            calorie_balance = total_calories - calorie_goal
            progress_percent = round((total_calories / calorie_goal) * 100, 1)

        return Response({
            'member_id': member.id,
            'member_name': member.get_full_name(),
            'date': target_date,
            'disclaimer': DIET_DISCLAIMER,
            'summary': {
                'total_calories_consumed': total_calories,
                'calorie_goal': calorie_goal,
                'calorie_balance': calorie_balance,  # negative = deficit, positive = surplus
                'calorie_balance_label': (
                    'on track' if calorie_balance is None
                    else ('deficit' if calorie_balance < 0 else ('surplus' if calorie_balance > 0 else 'exact'))
                ),
                'progress_percent': progress_percent,
                'macros': {
                    'protein_g': total_protein,
                    'carbs_g': total_carbs,
                    'fat_g': total_fat,
                    'protein_goal_g': protein_goal,
                    'carbs_goal_g': carbs_goal,
                    'fat_goal_g': fat_goal,
                },
            },
            'active_plan': {
                'id': active_plan.id,
                'name': active_plan.name,
                'goal': active_plan.goal,
            } if active_plan else None,
            'meal_logs': log_list,
        })
