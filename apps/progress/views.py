from datetime import date, timedelta
from collections import OrderedDict

from django.db.models import Min, Max, Count, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ProgressEntry, PersonalRecord
from .serializers import ProgressEntrySerializer, PersonalRecordSerializer


def _visible_qs(model, user):
    """Return the queryset a given user is allowed to see for this model."""
    if user.role in ['OWNER', 'STAFF']:
        return model.objects.all()
    if user.is_member:
        return model.objects.filter(member=user)
    from apps.trainers.models import TrainerMemberAssignment
    assigned_ids = TrainerMemberAssignment.objects.filter(
        trainer=user, is_active=True
    ).values_list('member_id', flat=True)
    return model.objects.filter(member_id__in=assigned_ids)


class ProgressEntryListCreateView(generics.ListCreateAPIView):
    serializer_class = ProgressEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(ProgressEntry, self.request.user)

    def perform_create(self, serializer):
        save_kwargs = {'recorded_by': self.request.user}
        if self.request.user.role == 'MEMBER':
            save_kwargs['member'] = self.request.user
        serializer.save(**save_kwargs)


class ProgressEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProgressEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(ProgressEntry, self.request.user)


class PersonalRecordListCreateView(generics.ListCreateAPIView):
    serializer_class = PersonalRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(PersonalRecord, self.request.user)

    def perform_create(self, serializer):
        save_kwargs = {}
        if self.request.user.role == 'MEMBER':
            save_kwargs['member'] = self.request.user
        serializer.save(**save_kwargs)


class PersonalRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PersonalRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(PersonalRecord, self.request.user)


class MemberStatsView(APIView):
    """Aggregated stats for the member progress dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role != 'MEMBER':
            return Response(
                {'detail': 'This endpoint is for members only.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        entries = ProgressEntry.objects.filter(member=user).order_by('date')
        first_entry = entries.first()
        latest_entry = entries.last()

        def entry_to_dict(e):
            if e is None:
                return None
            return {
                'date': str(e.date),
                'weight_kg': float(e.weight_kg) if e.weight_kg else None,
                'height_cm': float(e.height_cm) if e.height_cm else None,
                'body_fat_percentage': float(e.body_fat_percentage) if e.body_fat_percentage else None,
                'muscle_mass_kg': float(e.muscle_mass_kg) if e.muscle_mass_kg else None,
                'chest_cm': float(e.chest_cm) if e.chest_cm else None,
                'waist_cm': float(e.waist_cm) if e.waist_cm else None,
                'hips_cm': float(e.hips_cm) if e.hips_cm else None,
                'bicep_cm': float(e.bicep_cm) if e.bicep_cm else None,
                'thigh_cm': float(e.thigh_cm) if e.thigh_cm else None,
                'bmi': float(e.bmi) if e.bmi else None,
            }

        all_entries = [entry_to_dict(e) for e in entries]

        # Attendance stats
        from apps.attendance.models import Attendance
        today = date.today()
        first_day_of_month = today.replace(day=1)
        month_records = Attendance.objects.filter(
            user=user,
            date__gte=first_day_of_month,
            date__lte=today,
            status='PRESENT',
        )
        this_month_count = month_records.count()

        days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
        working_days_passed = today.day
        month_pct = round(this_month_count / working_days_passed * 100) if working_days_passed > 0 else 0

        # Current streak
        streak = 0
        check_date = today
        while True:
            if Attendance.objects.filter(user=user, date=check_date, status='PRESENT').exists():
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # Calendar heatmap (last 90 days)
        cal_start = today - timedelta(days=89)
        cal_records = set(
            Attendance.objects.filter(
                user=user,
                date__gte=cal_start,
                date__lte=today,
                status='PRESENT',
            ).values_list('date', flat=True)
        )
        calendar_90d = [str(d) for d in sorted(cal_records)]

        # Personal records summary: first and latest per exercise
        pr_exercises = (
            PersonalRecord.objects.filter(member=user)
            .values('exercise_id', 'exercise__name')
            .annotate(first_date=Min('date'), latest_date=Max('date'))
            .order_by('exercise__name')
        )
        pr_summary = []
        for ex in pr_exercises:
            first_pr = PersonalRecord.objects.filter(
                member=user, exercise_id=ex['exercise_id'], date=ex['first_date']
            ).first()
            latest_pr = PersonalRecord.objects.filter(
                member=user, exercise_id=ex['exercise_id'], date=ex['latest_date']
            ).first()
            pr_summary.append({
                'exercise': ex['exercise__name'],
                'exercise_id': ex['exercise_id'],
                'first': {'value': float(first_pr.value), 'unit': first_pr.unit, 'date': str(first_pr.date)} if first_pr else None,
                'latest': {'value': float(latest_pr.value), 'unit': latest_pr.unit, 'date': str(latest_pr.date)} if latest_pr else None,
            })

        # Member profile for goal info
        profile = getattr(user, 'member_profile', None)
        fitness_goal = profile.fitness_goal if profile else ''
        fitness_level = profile.fitness_level if profile else ''

        return Response({
            'first_entry': entry_to_dict(first_entry),
            'latest_entry': entry_to_dict(latest_entry),
            'all_entries': all_entries,
            'total_entries': entries.count(),
            'attendance': {
                'this_month': this_month_count,
                'days_in_month': days_in_month,
                'month_pct': month_pct,
                'streak': streak,
                'calendar_90d': calendar_90d,
            },
            'personal_records': pr_summary,
            'fitness_goal': fitness_goal,
            'fitness_level': fitness_level,
        })
