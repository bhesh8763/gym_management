from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import DietPlanViewSet, MealViewSet, MealLogViewSet, MealLogDailySummaryView

router = DefaultRouter()
router.register('diet-plans', DietPlanViewSet, basename='diet-plan')
router.register('meals',      MealViewSet,     basename='meal')
router.register('meal-logs',  MealLogViewSet,  basename='meal-log')

urlpatterns = [
    path('', include(router.urls)),
    # Daily summary sits outside the router to avoid conflicting with the
    # meal-logs/{id}/ detail route.
    path('meal-logs/daily-summary/', MealLogDailySummaryView.as_view(), name='meal-log-daily-summary'),
]
