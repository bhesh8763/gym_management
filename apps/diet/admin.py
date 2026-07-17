from django.contrib import admin
from .models import DietPlan, Meal


class MealInline(admin.TabularInline):
    model = Meal
    extra = 0


@admin.register(DietPlan)
class DietPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'member', 'trainer', 'goal', 'daily_calories', 'is_active')
    list_filter = ('goal', 'is_active')
    search_fields = ('name', 'member__email')
    inlines = [MealInline]
