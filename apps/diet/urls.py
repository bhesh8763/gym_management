from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import DietPlanViewSet, MealViewSet, MealLogViewSet, MealLogDailySummaryView

router = DefaultRouter()
router.register('diet-plans', DietPlanViewSet, basename='diet-plan')
router.register('meals',      MealViewSet,     basename='meal')
router.register('meal-logs',  MealLogViewSet,  basename='meal-log')

urlpatterns = [
    # Daily summary must come BEFORE the router so its path isn't swallowed
    # by the router's meal-logs/<pk>/ detail route.
    path('meal-logs/daily-summary/', MealLogDailySummaryView.as_view(), name='meal-log-daily-summary'),
    path('', include(router.urls)),
]
