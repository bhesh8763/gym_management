from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    DietPlanViewSet, MealViewSet, MealLogViewSet, MealLogDailySummaryView,
    EffectiveDietPlanView, MealChecklistViewSet,
)

router = DefaultRouter()
router.register('diet-plans',     DietPlanViewSet,      basename='diet-plan')
router.register('meals',          MealViewSet,          basename='meal')
router.register('meal-logs',      MealLogViewSet,       basename='meal-log')
router.register('meal-checklist', MealChecklistViewSet, basename='meal-checklist')

urlpatterns = [
    # These must come BEFORE the router so their paths aren't swallowed by
    # the router's <basename>/<pk>/ detail routes.
    path('meal-logs/daily-summary/', MealLogDailySummaryView.as_view(), name='meal-log-daily-summary'),
    path('effective-plan/',          EffectiveDietPlanView.as_view(),   name='effective-diet-plan'),
    path('', include(router.urls)),
]