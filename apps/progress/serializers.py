from datetime import date
from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import ProgressEntry, PersonalRecord

User = get_user_model()


class ProgressEntrySerializer(serializers.ModelSerializer):
    bmi = serializers.ReadOnlyField()
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='MEMBER'),
        required=False,
    )

    class Meta:
        model = ProgressEntry
        fields = "__all__"
        read_only_fields = ["recorded_by"]

    def validate(self, data):
        request = self.context.get('request')
        if request and request.user.role == 'MEMBER':
            data['member'] = request.user

        entry_date = data.get('date')
        if entry_date and entry_date > date.today():
            raise serializers.ValidationError({'date': 'Progress entries cannot be for future dates.'})

        weight = data.get('weight_kg')
        if weight is not None and (weight < 20 or weight > 300):
            raise serializers.ValidationError({'weight_kg': 'Weight must be between 20 and 300 kg.'})

        bf = data.get('body_fat_percentage')
        if bf is not None and (bf < 2 or bf > 60):
            raise serializers.ValidationError({'body_fat_percentage': 'Body fat must be between 2% and 60%.'})

        height = data.get('height_cm')
        if height is not None and (height < 50 or height > 300):
            raise serializers.ValidationError({'height_cm': 'Height must be between 50 and 300 cm.'})

        muscle = data.get('muscle_mass_kg')
        if muscle is not None and (muscle < 5 or muscle > 150):
            raise serializers.ValidationError({'muscle_mass_kg': 'Muscle mass must be between 5 and 150 kg.'})

        return data


class PersonalRecordSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source="exercise.name", read_only=True)
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='MEMBER'),
        required=False,
    )

    class Meta:
        model = PersonalRecord
        fields = "__all__"

    def validate(self, data):
        request = self.context.get('request')
        if request and request.user.role == 'MEMBER':
            data['member'] = request.user

        pr_date = data.get('date')
        if pr_date and pr_date > date.today():
            raise serializers.ValidationError({'date': 'Personal records cannot be for future dates.'})

        value = data.get('value')
        if value is not None and value <= 0:
            raise serializers.ValidationError({'value': 'Value must be a positive number.'})

        return data
