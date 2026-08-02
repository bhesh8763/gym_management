from django.urls import path

from .views import (
    DietPlanListCreateView,
    DietPlanDetailView,
    MealListCreateView,
    MealDetailView,
    MealLogListCreateView,
    MealLogDetailView,
    MealLogDailySummaryView,
)

urlpatterns = [
    path('plans/', DietPlanListCreateView.as_view(), name='diet-plan-list'),
    path('plans/<int:pk>/', DietPlanDetailView.as_view(), name='diet-plan-detail'),

    path('meals/', MealListCreateView.as_view(), name='meal-list'),
    path('meals/<int:pk>/', MealDetailView.as_view(), name='meal-detail'),

    path('meal-logs/', MealLogListCreateView.as_view(), name='meal-log-list'),
    path('meal-logs/<int:pk>/', MealLogDetailView.as_view(), name='meal-log-detail'),

    # Daily summary with calorie totals + goal comparison
    path('meal-logs/daily-summary/', MealLogDailySummaryView.as_view(), name='meal-log-daily-summary'),
]
