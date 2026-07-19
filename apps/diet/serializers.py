from rest_framework import serializers

from .models import DietPlan, Meal, MealLog


class MealSerializer(serializers.ModelSerializer):
    class Meta:
        model = Meal
        fields = "__all__"


class DietPlanSerializer(serializers.ModelSerializer):
    meals = MealSerializer(many=True, read_only=True)
    trainer = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = DietPlan
        fields = "__all__"


class MealLogSerializer(serializers.ModelSerializer):
    total_calories = serializers.ReadOnlyField()
    member = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = MealLog
        fields = "__all__"