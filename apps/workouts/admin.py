from django.contrib import admin
from .models import Exercise, WorkoutPlan, WorkoutDay, WorkoutDayExercise


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('name', 'muscle_group', 'exercise_type')
    list_filter = ('muscle_group', 'exercise_type')
    search_fields = ('name',)


class WorkoutDayInline(admin.TabularInline):
    model = WorkoutDay
    extra = 0


@admin.register(WorkoutPlan)
class WorkoutPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'member', 'trainer', 'difficulty', 'is_active', 'start_date')
    list_filter = ('difficulty', 'is_active')
    search_fields = ('name', 'member__email', 'trainer__email')
    inlines = [WorkoutDayInline]


class WorkoutDayExerciseInline(admin.TabularInline):
    model = WorkoutDayExercise
    extra = 0


@admin.register(WorkoutDay)
class WorkoutDayAdmin(admin.ModelAdmin):
    list_display = ('plan', 'day_number', 'day_name')
    inlines = [WorkoutDayExerciseInline]
