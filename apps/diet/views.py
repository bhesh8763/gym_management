# diet views
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

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
        return _visible_meal_logs(self.request.user)


class MealLogDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MealLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_meal_logs(self.request.user)