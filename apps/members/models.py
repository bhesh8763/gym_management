"""
Member profile model — extends the User account with fitness-specific info.
"""
from django.conf import settings
from django.db import models


class MemberProfile(models.Model):
    """
    One-to-one profile for users with role=MEMBER.
    Stores demographic and fitness baseline info.
    """

    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'
        OTHER = 'O', 'Other'
        PREFER_NOT = 'N', 'Prefer not to say'

    class FitnessGoal(models.TextChoices):
        WEIGHT_LOSS = 'WEIGHT_LOSS', 'Weight Loss'
        MUSCLE_GAIN = 'MUSCLE_GAIN', 'Muscle Gain'
        ENDURANCE = 'ENDURANCE', 'Endurance'
        FLEXIBILITY = 'FLEXIBILITY', 'Flexibility'
        GENERAL_FITNESS = 'GENERAL', 'General Fitness'
        REHABILITATION = 'REHAB', 'Rehabilitation'

    class FitnessLevel(models.TextChoices):
        BEGINNER = 'BEGINNER', 'Beginner'
        INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
        ADVANCED = 'ADVANCED', 'Advanced'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='member_profile',
    )
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    address = models.TextField(blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)

    # Fitness baseline
    height_cm = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Height in centimetres'
    )
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Weight in kilograms'
    )
    fitness_goal = models.CharField(
        max_length=20, choices=FitnessGoal.choices, blank=True
    )
    fitness_level = models.CharField(
        max_length=15, choices=FitnessLevel.choices, default=FitnessLevel.BEGINNER
    )

    # Medical / notes
    medical_conditions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'member_profiles'
        verbose_name = 'Member Profile'
        verbose_name_plural = 'Member Profiles'

    def __str__(self):
        return f'Profile: {self.user.get_full_name()}'

    @property
    def bmi(self):
        """Calculate BMI if height and weight are available."""
        if self.height_cm and self.weight_kg:
            h_m = float(self.height_cm) / 100
            return round(float(self.weight_kg) / (h_m ** 2), 2)
        return None
