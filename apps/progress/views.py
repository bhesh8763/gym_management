from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from .models import ProgressEntry, PersonalRecord
from .serializers import ProgressEntrySerializer, PersonalRecordSerializer


def _visible_qs(model, user):
    """Return the queryset a given user is allowed to see for this model."""
    if user.role in ['OWNER', 'STAFF']:
        return model.objects.all()
    if user.is_member:
        return model.objects.filter(member=user)
    # trainer: only members currently assigned to them
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
        serializer.save(recorded_by=self.request.user)


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


class PersonalRecordDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PersonalRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return _visible_qs(PersonalRecord, self.request.user)