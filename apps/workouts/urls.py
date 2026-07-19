
from django.urls import path

from .views import (
    ExerciseListCreateView,
    ExerciseDetailView,
    WorkoutPlanListCreateView,
    WorkoutPlanDetailView,
    WorkoutDayListCreateView,
    WorkoutDayDetailView,
    WorkoutDayExerciseListCreateView,
    WorkoutDayExerciseDetailView,
)

urlpatterns = [
    path('exercises/', ExerciseListCreateView.as_view(), name='exercise-list'),
    path('exercises/<int:pk>/', ExerciseDetailView.as_view(), name='exercise-detail'),

    path('plans/', WorkoutPlanListCreateView.as_view(), name='workout-plan-list'),
    path('plans/<int:pk>/', WorkoutPlanDetailView.as_view(), name='workout-plan-detail'),

    path('days/', WorkoutDayListCreateView.as_view(), name='workout-day-list'),
    path('days/<int:pk>/', WorkoutDayDetailView.as_view(), name='workout-day-detail'),

    path('day-exercises/', WorkoutDayExerciseListCreateView.as_view(), name='workout-day-exercise-list'),
    path('day-exercises/<int:pk>/', WorkoutDayExerciseDetailView.as_view(), name='workout-day-exercise-detail'),
]