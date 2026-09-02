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
    WorkoutTemplateVersionListView,
    WorkoutTemplateVersionRestoreView,
    WorkoutDayListCreateView,
    WorkoutDayDetailView,
    WorkoutDayMoveView,
    WorkoutDayExerciseListCreateView,
    WorkoutDayExerciseDetailView,
    WorkoutAssignmentListCreateView,
    WorkoutAssignmentDetailView,
    WorkoutCompletionLogListCreateView,
    AssignmentPauseView,
    AssignmentResumeView,
    AssignmentCancelView,
    TrainerMessageView,
    TrainerMessagesView,
    TrainerReplyView,
    WorkoutCompletionLogExportView,
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
    path('templates/<int:pk>/versions/', WorkoutTemplateVersionListView.as_view(), name='workout-template-version-list'),
    path('templates/<int:pk>/versions/<int:version_id>/restore/', WorkoutTemplateVersionRestoreView.as_view(), name='workout-template-version-restore'),

    # Builder: days + exercises within a template
    path('days/', WorkoutDayListCreateView.as_view(), name='workout-day-list'),
    path('days/<int:pk>/', WorkoutDayDetailView.as_view(), name='workout-day-detail'),
    path('days/<int:pk>/move/', WorkoutDayMoveView.as_view(), name='workout-day-move'),
    path('day-exercises/', WorkoutDayExerciseListCreateView.as_view(), name='workout-day-exercise-list'),
    path('day-exercises/<int:pk>/', WorkoutDayExerciseDetailView.as_view(), name='workout-day-exercise-detail'),

    # Assignments: template <-> member
    path('assignments/', WorkoutAssignmentListCreateView.as_view(), name='workout-assignment-list'),
    path('assignments/<int:pk>/', WorkoutAssignmentDetailView.as_view(), name='workout-assignment-detail'),

    # Member-facing completion logs (drives Progress tab)
    path('completion-logs/', WorkoutCompletionLogListCreateView.as_view(), name='workout-completion-log-list'),

    # Member self-service actions
    path('assignments/<int:pk>/pause/', AssignmentPauseView.as_view(), name='assignment-pause'),
    path('assignments/<int:pk>/resume/', AssignmentResumeView.as_view(), name='assignment-resume'),
    path('assignments/<int:pk>/cancel/', AssignmentCancelView.as_view(), name='assignment-cancel'),

    # Trainer messaging (via notifications)
    path('message-trainer/', TrainerMessageView.as_view(), name='message-trainer'),
    path('trainer-messages/', TrainerMessagesView.as_view(), name='trainer-messages'),
    path('trainer-reply/', TrainerReplyView.as_view(), name='trainer-reply'),

    # CSV Export
    path('export-csv/', WorkoutCompletionLogExportView.as_view(), name='workout-export-csv'),
]