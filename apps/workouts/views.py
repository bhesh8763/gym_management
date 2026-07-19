# workouts views
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsOwnerOrStaffOrTrainer

from .models import Exercise, WorkoutPlan, WorkoutDay, WorkoutDayExercise
from .serializers import (
    ExerciseSerializer,
    WorkoutPlanSerializer,
    WorkoutDaySerializer,
    WorkoutDayExerciseSerializer,
)


def _visible_plans(user):
    if user.role in ['OWNER', 'STAFF']:
        return WorkoutPlan.objects.all()
    if user.is_member:
        return WorkoutPlan.objects.filter(member=user)
    if user.is_trainer:
        return WorkoutPlan.objects.filter(trainer=user)
    return WorkoutPlan.objects.none()


class ExerciseListCreateView(generics.ListCreateAPIView):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ExerciseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticated]


class WorkoutPlanListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkoutPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsOwnerOrStaffOrTrainer()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return _visible_plans(self.request.user)


class WorkoutPlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WorkoutPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_plans(self.request.user)


class WorkoutDayListCreateView(generics.ListCreateAPIView):
    queryset = WorkoutDay.objects.all()
    serializer_class = WorkoutDaySerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


class WorkoutDayDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkoutDay.objects.all()
    serializer_class = WorkoutDaySerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


class WorkoutDayExerciseListCreateView(generics.ListCreateAPIView):
    queryset = WorkoutDayExercise.objects.all()
    serializer_class = WorkoutDayExerciseSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]


class WorkoutDayExerciseDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WorkoutDayExercise.objects.all()
    serializer_class = WorkoutDayExerciseSerializer
    permission_classes = [IsOwnerOrStaffOrTrainer]