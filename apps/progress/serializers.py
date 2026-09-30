from datetime import date
from rest_framework import serializers
from django.contrib.auth import get_user_model

from apps.gyms.tenancy import user_has_branch_access

from .models import ProgressEntry, PersonalRecord

User = get_user_model()


class ProgressEntrySerializer(serializers.ModelSerializer):
    bmi = serializers.ReadOnlyField()
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
    )

    class Meta:
        model = ProgressEntry
        fields = "__all__"
        read_only_fields = ["gym", "branch", "recorded_by"]
        validators = []  # Disable auto-generated UniqueTogetherValidator

    def validate(self, data):
        request = self.context.get('request')
        if request:
            role = getattr(request, 'gym_role', request.user.role)
            if role == 'MEMBER':
                data['member'] = request.user
            gym = getattr(request, 'gym', None)
            if gym and data.get('member'):
                from apps.gyms.models import GymMembership
                if not GymMembership.objects.filter(
                    gym=gym, user=data['member'], role=GymMembership.Role.MEMBER,
                    status=GymMembership.Status.ACTIVE,
                ).exists():
                    raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
                if not user_has_branch_access(data['member'], gym, getattr(request, 'branch', None)):
                    raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
        else:
            member = data.get('member', getattr(self.instance, 'member', None))
            if member is not None and member.role != 'MEMBER':
                raise serializers.ValidationError({'member': 'The selected user is not a member.'})
        member = data.get('member', getattr(self.instance, 'member', None))
        entry_date = data.get('date')
        if member and entry_date:
            instance = self.instance
            qs = ProgressEntry.objects.filter(
                gym_id=(
                    getattr(self.context.get('request'), 'gym_id', None)
                    if self.context.get('request') is not None
                    else getattr(self.instance, 'gym_id', None)
                ),
                member=member,
                date=entry_date,
            )
            if instance:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'date': 'A progress entry for this member on this date already exists.'})

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
    exercise_muscle_group = serializers.CharField(source="exercise.muscle_group", read_only=True)
    member = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
    )

    class Meta:
        model = PersonalRecord
        fields = "__all__"
        read_only_fields = ["gym", "branch"]
        validators = []  # Disable auto-generated UniqueTogetherValidator

    def validate(self, data):
        request = self.context.get('request')
        if request:
            role = getattr(request, 'gym_role', request.user.role)
            if role == 'MEMBER':
                data['member'] = request.user
            gym = getattr(request, 'gym', None)
            if gym and data.get('member'):
                from apps.gyms.models import GymMembership
                if not GymMembership.objects.filter(
                    gym=gym, user=data['member'], role=GymMembership.Role.MEMBER,
                    status=GymMembership.Status.ACTIVE,
                ).exists():
                    raise serializers.ValidationError({'member': 'Member is not active in this gym.'})
                if not user_has_branch_access(data['member'], gym, getattr(request, 'branch', None)):
                    raise serializers.ValidationError({'member': 'Member does not have access to this branch.'})
        else:
            member = data.get('member', getattr(self.instance, 'member', None))
            if member is not None and member.role != 'MEMBER':
                raise serializers.ValidationError({'member': 'The selected user is not a member.'})
        member = data.get('member', getattr(self.instance, 'member', None))
        exercise = data.get('exercise', getattr(self.instance, 'exercise', None))
        pr_date = data.get('date')
        if member and exercise and pr_date:
            instance = self.instance
            qs = PersonalRecord.objects.filter(
                gym_id=(
                    getattr(self.context.get('request'), 'gym_id', None)
                    if self.context.get('request') is not None
                    else getattr(self.instance, 'gym_id', None)
                ),
                member=member,
                exercise=exercise,
                date=pr_date,
            )
            if instance:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'date': 'A personal record for this exercise on this date already exists.'})

        pr_date = data.get('date')
        if pr_date and pr_date > date.today():
            raise serializers.ValidationError({'date': 'Personal records cannot be for future dates.'})

        value = data.get('value')
        if value is not None and value <= 0:
            raise serializers.ValidationError({'value': 'Value must be a positive number.'})

        return data
