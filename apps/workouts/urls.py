from django.urls import path

from .views import (
    ExerciseListCreateView,
    ExerciseDetailView,
    WorkoutTemplateListCreateView,
    WorkoutTemplateDetailView,
    WorkoutTemplateSubmitReviewView,
    WorkoutTemplateApproveView,
    WorkoutTemplateArchiveView,
    WorkoutTemplateDuplicateView,
    WorkoutDayListCreateView,
    WorkoutDayDetailView,
    WorkoutDayExerciseListCreateView,
    WorkoutDayExerciseDetailView,
    WorkoutAssignmentListCreateView,
    WorkoutAssignmentDetailView,
    WorkoutCompletionLogListCreateView,
)

urlpatterns = [
    # Exercise Library
    path('exercises/', ExerciseListCreateView.as_view(), name='exercise-list'),
    path('exercises/<int:pk>/', ExerciseDetailView.as_view(), name='exercise-detail'),

    # Workout Templates (+ approval workflow actions)
    path('templates/', WorkoutTemplateListCreateView.as_view(), name='workout-template-list'),
    path('templates/<int:pk>/', WorkoutTemplateDetailView.as_view(), name='workout-template-detail'),
    path('templates/<int:pk>/submit-review/', WorkoutTemplateSubmitReviewView.as_view(), name='workout-template-submit-review'),
    path('templates/<int:pk>/approve/', WorkoutTemplateApproveView.as_view(), name='workout-template-approve'),
    path('templates/<int:pk>/archive/', WorkoutTemplateArchiveView.as_view(), name='workout-template-archive'),
    path('templates/<int:pk>/duplicate/', WorkoutTemplateDuplicateView.as_view(), name='workout-template-duplicate'),

    # Builder: days + exercises within a template
    path('days/', WorkoutDayListCreateView.as_view(), name='workout-day-list'),
    path('days/<int:pk>/', WorkoutDayDetailView.as_view(), name='workout-day-detail'),
    path('day-exercises/', WorkoutDayExerciseListCreateView.as_view(), name='workout-day-exercise-list'),
    path('day-exercises/<int:pk>/', WorkoutDayExerciseDetailView.as_view(), name='workout-day-exercise-detail'),

    # Assignments: template <-> member
    path('assignments/', WorkoutAssignmentListCreateView.as_view(), name='workout-assignment-list'),
    path('assignments/<int:pk>/', WorkoutAssignmentDetailView.as_view(), name='workout-assignment-detail'),

    # Member-facing completion logs (drives Progress tab)
    path('completion-logs/', WorkoutCompletionLogListCreateView.as_view(), name='workout-completion-log-list'),
]