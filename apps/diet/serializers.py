from rest_framework import serializers

from .models import DietPlan, Meal, MealLog


class MealSerializer(serializers.ModelSerializer):
    """Serializer for individual meal entries within a diet plan."""

    meal_type_display = serializers.CharField(source='get_meal_type_display', read_only=True)

    class Meta:
        model  = Meal
        fields = [
            'id', 'diet_plan', 'meal_type', 'meal_type_display',
            'food_name', 'portion', 'calories',
            'time_suggestion', 'notes',
        ]
        read_only_fields = ['id']


class MealInlineSerializer(serializers.ModelSerializer):
    """Lightweight meal serializer used for nested creation inside DietPlan."""

    meal_type_display = serializers.CharField(source='get_meal_type_display', read_only=True)

    class Meta:
        model  = Meal
        fields = [
            'id', 'meal_type', 'meal_type_display',
            'food_name', 'portion', 'calories',
            'time_suggestion', 'notes',
        ]
        read_only_fields = ['id']


class DietPlanSerializer(serializers.ModelSerializer):
    """
    Full serializer for DietPlan.

    Supports:
    - Nested meal creation via `meals` list on POST/PUT.
    - `created_by` is injected automatically from request.user;
      it is never required (or accepted) from request body.
    - Read-only computed fields: `created_by_name`, `member_name`, `status`.
    """

    meals            = MealInlineSerializer(many=True, required=False)
    created_by_name  = serializers.CharField(source='created_by.get_full_name', read_only=True)
    member_name      = serializers.CharField(source='member.get_full_name',     read_only=True)
    # Human-readable status label
    status           = serializers.SerializerMethodField()
    goal_display     = serializers.CharField(source='get_goal_display', read_only=True)

    class Meta:
        model  = DietPlan
        fields = [
            'id', 'name', 'goal', 'goal_display',
            'daily_calories', 'protein_g', 'carbs_g', 'fats_g',
            'is_active', 'status',
            'member', 'member_name',
            'created_by', 'created_by_name',
            'notes', 'start_date', 'end_date',
            'created_at', 'updated_at',
            'meals',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_status(self, obj):
        return 'Active' if obj.is_active else 'Inactive'

    def create(self, validated_data):
        # Pop nested meals before creating the plan
        meals_data = validated_data.pop('meals', [])
        # Inject the authenticated user as creator
        validated_data['created_by'] = self.context['request'].user
        diet_plan = DietPlan.objects.create(**validated_data)
        for meal_data in meals_data:
            Meal.objects.create(diet_plan=diet_plan, **meal_data)
        return diet_plan

    def update(self, instance, validated_data):
        # On update, replace meals entirely if provided
        meals_data = validated_data.pop('meals', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if meals_data is not None:
            instance.meals.all().delete()
            for meal_data in meals_data:
                Meal.objects.create(diet_plan=instance, **meal_data)
        return instance


class MealLogSerializer(serializers.ModelSerializer):
    """Serializer for a member's daily meal log entries."""

    total_calories = serializers.ReadOnlyField()
    # member is injected by the view, never supplied by the client
    member = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model  = MealLog
        fields = [
            'id', 'member', 'date',
            'food_items', 'total_calories',
            'notes', 'created_at',
        ]
        read_only_fields = ['id', 'total_calories', 'created_at']
