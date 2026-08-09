from django.contrib import admin
from .models import DietPlan, Meal, MealLog


class MealInline(admin.TabularInline):
    model = Meal
    extra = 0


@admin.register(DietPlan)
class DietPlanAdmin(admin.ModelAdmin):
    list_display  = ('name', 'member', 'created_by', 'goal', 'daily_calories', 'is_active')
    list_filter   = ('goal', 'is_active')
    search_fields = ('name', 'member__email', 'created_by__email')
    inlines       = [MealInline]


@admin.register(MealLog)
class MealLogAdmin(admin.ModelAdmin):
    list_display   = ('member', 'date', 'total_calories')
    search_fields  = ('member__email', 'member__first_name')
    date_hierarchy = 'date'
