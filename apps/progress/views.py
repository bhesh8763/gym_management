from datetime import date, timedelta
from collections import OrderedDict

from django.db.models import Min, Max, Count, Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.tenancy import tenant_queryset

from .models import ProgressEntry, PersonalRecord
from .serializers import ProgressEntrySerializer, PersonalRecordSerializer


def _visible_qs(model, user, request=None):
    """Return the queryset a given user is allowed to see for this model."""
    role = getattr(request, 'gym_role', user.role) if request is not None else user.role
    if role in ['OWNER', 'STAFF']:
        qs = model.objects.all()
    elif role == 'MEMBER':
        qs = model.objects.filter(member=user)
    else:
        from apps.trainers.models import TrainerMemberAssignment
        assigned_ids = TrainerMemberAssignment.objects.filter(
            trainer=user, is_active=True
        ).values_list('member_id', flat=True)
        qs = model.objects.filter(member_id__in=assigned_ids)

    # Apply optional ?member= filter for non-member roles
    if request and getattr(request, 'gym_role', user.role) in ['OWNER', 'STAFF', 'TRAINER']:
        member_id = request.query_params.get('member')
        if member_id:
            qs = qs.filter(member_id=member_id)
    return tenant_queryset(qs, request)


class ProgressEntryListCreateView(generics.ListCreateAPIView):
    serializer_class = ProgressEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(ProgressEntry, self.request.user, self.request)

    def perform_create(self, serializer):
        save_kwargs = {'recorded_by': self.request.user}
        if getattr(self.request, 'gym_role', self.request.user.role) == 'MEMBER':
            save_kwargs['member'] = self.request.user
        save_kwargs['gym'] = getattr(self.request, 'gym', None)
        save_kwargs['branch'] = getattr(self.request, 'branch', None)
        serializer.save(**save_kwargs)


class ProgressEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProgressEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(ProgressEntry, self.request.user, self.request)


class PersonalRecordListCreateView(generics.ListCreateAPIView):
    serializer_class = PersonalRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(PersonalRecord, self.request.user, self.request)

    def perform_create(self, serializer):
        save_kwargs = {}
        if getattr(self.request, 'gym_role', self.request.user.role) == 'MEMBER':
            save_kwargs['member'] = self.request.user
        save_kwargs['gym'] = getattr(self.request, 'gym', None)
        save_kwargs['branch'] = getattr(self.request, 'branch', None)
        serializer.save(**save_kwargs)


class PersonalRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PersonalRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(PersonalRecord, self.request.user, self.request)


class MemberStatsView(APIView):
    """Aggregated stats for the member progress dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if getattr(request, 'gym_role', user.role) != 'MEMBER':
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
        month_records = tenant_queryset(
            Attendance.objects.filter(
                user=user,
                date__gte=first_day_of_month,
                date__lte=today,
                status='PRESENT',
            ),
            request,
        )
        this_month_count = month_records.count()

        days_in_month = (today.replace(month=today.month % 12 + 1, day=1) - timedelta(days=1)).day if today.month < 12 else 31
        working_days_passed = today.day
        month_pct = round(this_month_count / working_days_passed * 100) if working_days_passed > 0 else 0

        # Current streak
        streak = 0
        check_date = today
        while True:
            if tenant_queryset(
                Attendance.objects.filter(user=user, date=check_date, status='PRESENT'),
                request,
            ).exists():
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # Calendar heatmap (last 90 days)
        cal_start = today - timedelta(days=89)
        cal_records = set(
            tenant_queryset(
                Attendance.objects.filter(
                    user=user,
                    date__gte=cal_start,
                    date__lte=today,
                    status='PRESENT',
                ),
                request,
            ).values_list('date', flat=True)
        )
        calendar_90d = [str(d) for d in sorted(cal_records)]

        # Personal records summary: first and latest per exercise
        pr_exercises = (
            tenant_queryset(PersonalRecord.objects.filter(member=user), request)
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
        gym = getattr(request, 'gym', None)
        if gym:
            profile_qs = user.member_profiles.filter(gym=gym)
            branch = getattr(request, 'branch', None)
            if branch is not None:
                profile_qs = profile_qs.filter(
                    Q(branch=branch) | Q(branch__isnull=True)
                )
            profile = profile_qs.first()
        else:
            profile = user.member_profile
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
