from django.contrib import admin
from .models import (
    Exercise,
    WorkoutTemplate,
    WorkoutDay,
    WorkoutDayExercise,
    WorkoutAssignment,
    WorkoutCompletionLog,
    WorkoutTemplateVersion,
)


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('name', 'muscle_group', 'exercise_type', 'equipment')
    list_filter = ('muscle_group', 'exercise_type')
    search_fields = ('name',)


class WorkoutDayInline(admin.TabularInline):
    model = WorkoutDay
    extra = 0


@admin.register(WorkoutTemplate)
class WorkoutTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'goal', 'difficulty', 'status', 'trainer', 'duration_weeks', 'assigned_member_count')
    list_filter = ('status', 'difficulty')
    search_fields = ('name', 'trainer__email')
    inlines = [WorkoutDayInline]

    @admin.display(description='Assigned')
    def assigned_member_count(self, obj):
        return obj.get_assigned_member_count()


class WorkoutDayExerciseInline(admin.TabularInline):
    model = WorkoutDayExercise
    extra = 0


@admin.register(WorkoutDay)
class WorkoutDayAdmin(admin.ModelAdmin):
    list_display = ('template', 'week_number', 'day_number', 'day_name')
    inlines = [WorkoutDayExerciseInline]


@admin.register(WorkoutAssignment)
class WorkoutAssignmentAdmin(admin.ModelAdmin):
    list_display = ('template', 'member', 'status', 'start_date', 'end_date', 'completion_pct')
    list_filter = ('status',)
    search_fields = ('template__name', 'member__email')

    @admin.display(description='Progress')
    def completion_pct(self, obj):
        return f'{obj.completion_pct}%'


@admin.register(WorkoutCompletionLog)
class WorkoutCompletionLogAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'workout_day', 'date', 'status', 'perceived_difficulty')
    list_filter = ('status',)


@admin.register(WorkoutTemplateVersion)
class WorkoutTemplateVersionAdmin(admin.ModelAdmin):
    list_display = ('template', 'reason', 'created_by', 'created_at')
    list_filter = ('reason',)
    readonly_fields = ('snapshot',)