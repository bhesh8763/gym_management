"""
Workout plan management: exercise library, reusable templates,
per-member assignments, and completion logging.

Architecture (post-redesign):
    Exercise            — global library, created once, reused everywhere
    WorkoutTemplate      — reusable program (weeks/days/exercises), NOT tied to a member
    WorkoutDay            \\_ children of a template
    WorkoutDayExercise    /
    WorkoutAssignment    — links one WorkoutTemplate to one member, with its own
                            timeline and status. A template can have many assignments.
    WorkoutCompletionLog  — a member's actual session log against an assignment.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Exercise(models.Model):
    """
    Global exercise library. Trainers and owners add exercises here once;
    templates only ever reference them, never redefine them.
    """

    class MuscleGroup(models.TextChoices):
        CHEST = 'CHEST', 'Chest'
        BACK = 'BACK', 'Back'
        SHOULDERS = 'SHOULDERS', 'Shoulders'
        ARMS = 'ARMS', 'Arms'
        LEGS = 'LEGS', 'Legs'
        CORE = 'CORE', 'Core'
        FULL_BODY = 'FULL_BODY', 'Full Body'
        CARDIO = 'CARDIO', 'Cardio'

    class ExerciseType(models.TextChoices):
        STRENGTH = 'STRENGTH', 'Strength'
        CARDIO = 'CARDIO', 'Cardio'
        FLEXIBILITY = 'FLEXIBILITY', 'Flexibility'
        BALANCE = 'BALANCE', 'Balance'
        PLYOMETRIC = 'PLYO', 'Plyometric'

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    muscle_group = models.CharField(max_length=15, choices=MuscleGroup.choices)
    exercise_type = models.CharField(max_length=15, choices=ExerciseType.choices)
    equipment = models.CharField(max_length=100, blank=True, help_text='e.g. Barbell, Dumbbell, Bodyweight')
    instructions = models.TextField(blank=True)
    common_mistakes = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    image = models.ImageField(upload_to='exercises/', null=True, blank=True)
    alternative_exercises = models.ManyToManyField(
        'self', blank=True, symmetrical=True,
        help_text='Swappable substitutes shown when a member cannot perform this exercise.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exercises_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exercises'
        verbose_name = 'Exercise'
        verbose_name_plural = 'Exercises'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.muscle_group})'


class WorkoutTemplate(models.Model):
    """
    A reusable training program. Not tied to any member — build once,
    assign to as many members as needed via WorkoutAssignment.
    """

    class Difficulty(models.TextChoices):
        BEGINNER = 'BEGINNER', 'Beginner'
        INTERMEDIATE = 'INTERMEDIATE', 'Intermediate'
        ADVANCED = 'ADVANCED', 'Advanced'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        IN_REVIEW = 'IN_REVIEW', 'In review'
        APPROVED = 'APPROVED', 'Approved'
        ARCHIVED = 'ARCHIVED', 'Archived'

    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='workout_templates_created',
        limit_choices_to={'role': 'TRAINER'},
    )
    name = models.CharField(max_length=150)
    goal = models.CharField(
        max_length=100, blank=True,
        help_text='e.g. Fat Loss, Hypertrophy, Strength, Mobility',
    )
    description = models.TextField(blank=True)
    difficulty = models.CharField(
        max_length=15, choices=Difficulty.choices, default=Difficulty.BEGINNER
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT,
        help_text='Draft → In review → Approved → Archived',
    )
    duration_weeks = models.PositiveIntegerField(default=4)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='workout_templates_reviewed',
        limit_choices_to={'role__in': ['OWNER', 'STAFF']},
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workout_templates'
        verbose_name = 'Workout Template'
        verbose_name_plural = 'Workout Templates'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

    def submit_for_review(self, actor=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError('Only draft templates can be submitted for review.')
        self.status = self.Status.IN_REVIEW
        self.save(update_fields=['status', 'updated_at'])
        self._capture_version('submitted_for_review', actor)

    def approve(self, reviewer):
        if self.status != self.Status.IN_REVIEW:
            raise ValidationError('Only templates in review can be approved.')
        self.status = self.Status.APPROVED
        self.reviewed_by = reviewer
        self.save(update_fields=['status', 'reviewed_by', 'updated_at'])
        self._capture_version('approved', reviewer)

    def _capture_version(self, reason, actor):
        WorkoutTemplateVersion.objects.create(
            template=self, snapshot=WorkoutTemplateVersion.snapshot_of(self),
            reason=reason, created_by=actor,
        )

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.save(update_fields=['status', 'updated_at'])

    def clone(self, new_name=None):
        """Deep-copies this template (days + exercises) as a new Draft."""
        clone = WorkoutTemplate.objects.create(
            trainer=self.trainer,
            name=new_name or f'{self.name} (Copy)',
            goal=self.goal,
            description=self.description,
            difficulty=self.difficulty,
            status=WorkoutTemplate.Status.DRAFT,
            duration_weeks=self.duration_weeks,
        )
        for day in self.days.all():
            new_day = WorkoutDay.objects.create(
                template=clone,
                week_number=day.week_number,
                day_number=day.day_number,
                day_name=day.day_name,
                notes=day.notes,
            )
            for ex in day.exercises.all():
                WorkoutDayExercise.objects.create(
                    workout_day=new_day,
                    exercise=ex.exercise,
                    order=ex.order,
                    sets=ex.sets,
                    reps=ex.reps,
                    duration_seconds=ex.duration_seconds,
                    rest_seconds=ex.rest_seconds,
                    tempo=ex.tempo,
                    rpe=ex.rpe,
                    weight_kg=ex.weight_kg,
                    notes=ex.notes,
                )
        return clone

    def get_assigned_member_count(self):
        """
        Live count. Views that list many templates annotate this same value
        onto the queryset instead (avoids one query per row) — this method is
        for the single-object cases that don't go through that queryset:
        admin's list_display, and the response right after create().
        """
        return self.assignments.filter(status=WorkoutAssignment.Status.ACTIVE).count()


class WorkoutDay(models.Model):
    """A single day/session within a template."""

    template = models.ForeignKey(
        WorkoutTemplate, on_delete=models.CASCADE, related_name='days'
    )
    week_number = models.PositiveIntegerField(default=1)
    day_number = models.PositiveIntegerField(help_text='e.g. Day 1, Day 2')
    day_name = models.CharField(max_length=50, blank=True, help_text='e.g. Push Day')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workout_days'
        verbose_name = 'Workout Day'
        verbose_name_plural = 'Workout Days'
        ordering = ['week_number', 'day_number']
        unique_together = [('template', 'week_number', 'day_number')]

    def __str__(self):
        return f'{self.template.name} — Week {self.week_number} Day {self.day_number}'


class WorkoutDayExercise(models.Model):
    """An exercise placed on a specific day, with its own set/rep/rest scheme."""

    workout_day = models.ForeignKey(
        WorkoutDay, on_delete=models.CASCADE, related_name='exercises'
    )
    exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name='day_placements'
    )
    order = models.PositiveIntegerField(default=1)
    sets = models.PositiveIntegerField(null=True, blank=True)
    reps = models.CharField(max_length=20, blank=True, help_text='e.g. "10", "8-12", "AMRAP", "Failure"')
    duration_seconds = models.PositiveIntegerField(null=True, blank=True, help_text='For timed exercises (e.g. plank)')
    rest_seconds = models.PositiveIntegerField(default=60)
    tempo = models.CharField(max_length=15, blank=True, help_text='e.g. "2-0-2" (eccentric-pause-concentric)')
    rpe = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Rate of Perceived Exertion, 1-10')
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workout_day_exercises'
        verbose_name = 'Workout Day Exercise'
        verbose_name_plural = 'Workout Day Exercises'
        ordering = ['order']

    def __str__(self):
        return f'{self.workout_day} — {self.exercise.name}'


class WorkoutAssignment(models.Model):
    """
    Links one WorkoutTemplate to one member. This is the only place a
    member ever appears in the workout module — templates stay reusable.
    """

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        PAUSED = 'PAUSED', 'Paused'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    template = models.ForeignKey(
        WorkoutTemplate, on_delete=models.CASCADE, related_name='assignments'
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workout_assignments',
        limit_choices_to={'role': 'MEMBER'},
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='workout_assignments_made',
        limit_choices_to={'role__in': ['TRAINER', 'OWNER', 'STAFF']},
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text='Auto-filled from template duration if left blank')
    goal_note = models.CharField(max_length=200, blank=True, help_text='e.g. "prep for tournament"')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'workout_assignments'
        verbose_name = 'Workout Assignment'
        verbose_name_plural = 'Workout Assignments'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'member'],
                condition=models.Q(status='ACTIVE'),
                name='one_active_assignment_per_member_per_template',
            )
        ]

    def __str__(self):
        return f'{self.template.name} → {self.member.get_full_name()}'

    def save(self, *args, **kwargs):
        if not self.end_date and self.template_id:
            from datetime import timedelta
            from django.utils.dateparse import parse_date
            # start_date is normally already a date object (the API validates
            # it through the serializer field), but anything that writes via
            # the raw ORM — the admin, a data migration, a management command —
            # can hand this a plain string. Don't let arithmetic below blow up.
            start = self.start_date
            if isinstance(start, str):
                start = parse_date(start)
            if start:
                self.end_date = start + timedelta(weeks=self.template.duration_weeks)
        super().save(*args, **kwargs)

    @property
    def completion_pct(self):
        total = self.template.days.count()
        if not total:
            return 0
        done = self.logs.filter(status=WorkoutCompletionLog.Status.COMPLETED).values('workout_day').distinct().count()
        return round((done / total) * 100)


class WorkoutTemplateVersion(models.Model):
    """
    A point-in-time snapshot of a template's structure (days + exercises),
    captured at meaningful transitions — submit-for-review and approve —
    not on every keystroke. Lets a trainer or owner see what changed and
    roll back a template that was edited into a worse state after approval.
    """
    template = models.ForeignKey(
        WorkoutTemplate, on_delete=models.CASCADE, related_name='versions'
    )
    snapshot = models.JSONField(help_text='Serialized days + exercises at the time this version was captured.')
    reason = models.CharField(max_length=50, help_text='e.g. "submitted_for_review", "approved", "manual"')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='workout_template_versions_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workout_template_versions'
        verbose_name = 'Workout Template Version'
        verbose_name_plural = 'Workout Template Versions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.template.name} — v@{self.created_at:%Y-%m-%d %H:%M}'

    @staticmethod
    def snapshot_of(template):
        """Builds the JSON-serializable structure captured for a version."""
        return {
            'name': template.name,
            'goal': template.goal,
            'description': template.description,
            'difficulty': template.difficulty,
            'duration_weeks': template.duration_weeks,
            'days': [
                {
                    'week_number': day.week_number,
                    'day_number': day.day_number,
                    'day_name': day.day_name,
                    'notes': day.notes,
                    'exercises': [
                        {
                            'exercise_id': ex.exercise_id,
                            'exercise_name': ex.exercise.name,
                            'order': ex.order,
                            'sets': ex.sets,
                            'reps': ex.reps,
                            'rest_seconds': ex.rest_seconds,
                            'tempo': ex.tempo,
                            'rpe': ex.rpe,
                            'weight_kg': str(ex.weight_kg) if ex.weight_kg is not None else None,
                            'notes': ex.notes,
                        }
                        for ex in day.exercises.all()
                    ],
                }
                for day in template.days.all()
            ],
        }

    def restore(self):
        """Replaces the live template's days/exercises with this snapshot's."""
        template = self.template
        template.name = self.snapshot['name']
        template.goal = self.snapshot['goal']
        template.description = self.snapshot['description']
        template.difficulty = self.snapshot['difficulty']
        template.duration_weeks = self.snapshot['duration_weeks']
        template.save()

        template.days.all().delete()  # cascades to WorkoutDayExercise
        for day_data in self.snapshot['days']:
            day = WorkoutDay.objects.create(
                template=template,
                week_number=day_data['week_number'],
                day_number=day_data['day_number'],
                day_name=day_data['day_name'],
                notes=day_data['notes'],
            )
            for ex_data in day_data['exercises']:
                WorkoutDayExercise.objects.create(
                    workout_day=day,
                    exercise_id=ex_data['exercise_id'],
                    order=ex_data['order'],
                    sets=ex_data['sets'],
                    reps=ex_data['reps'],
                    rest_seconds=ex_data['rest_seconds'],
                    tempo=ex_data['tempo'],
                    rpe=ex_data['rpe'],
                    weight_kg=ex_data['weight_kg'],
                    notes=ex_data['notes'],
                )
        return template


class WorkoutCompletionLog(models.Model):
    """A member's actual result for one day of an assignment."""

    class Status(models.TextChoices):
        COMPLETED = 'COMPLETED', 'Completed'
        SKIPPED = 'SKIPPED', 'Skipped'
        PARTIAL = 'PARTIAL', 'Partial'

    assignment = models.ForeignKey(
        WorkoutAssignment, on_delete=models.CASCADE, related_name='logs'
    )
    workout_day = models.ForeignKey(
        WorkoutDay, on_delete=models.CASCADE, related_name='completion_logs'
    )
    date = models.DateField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.COMPLETED)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    calories = models.PositiveIntegerField(null=True, blank=True)
    perceived_difficulty = models.PositiveSmallIntegerField(null=True, blank=True, help_text='1-10')
    pain_level = models.PositiveSmallIntegerField(null=True, blank=True, help_text='0-10, 0 = none')
    set_logs = models.JSONField(
        default=list, blank=True,
        help_text='Per-set data, e.g. [{"set":1,"weight":80,"reps":10},{"set":2,"weight":80,"reps":8}]',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'workout_completion_logs'
        verbose_name = 'Workout Completion Log'
        verbose_name_plural = 'Workout Completion Logs'
        ordering = ['-date']
        unique_together = [('assignment', 'workout_day', 'date')]

    def __str__(self):
        return f'{self.assignment.member.get_full_name()} — {self.workout_day} ({self.status})'