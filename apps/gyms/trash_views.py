"""
Trash API — list / restore / purge soft-deleted records.

Endpoints (Owner/Staff only):
    GET    /api/gyms/trash/                    — summary counts per category
    GET    /api/gyms/trash/<slug>/             — list soft-deleted rows for one category
    POST   /api/gyms/trash/<slug>/<id>/restore/ — bring a row back
    DELETE /api/gyms/trash/<slug>/<id>/        — purge permanently (hard delete)
"""
import logging

from django.contrib.auth import get_user_model
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwnerOrStaff
from apps.gyms.services import record_audit
from apps.gyms.trash import TRASH_REGISTRY, deleted_queryset, get_model, get_serializer_class

logger = logging.getLogger(__name__)
User = get_user_model()


class TrashSummaryView(APIView):
    """GET /api/gyms/trash/ — item counts per trash category for the active gym."""

    permission_classes = [IsOwnerOrStaff]

    def get(self, request):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        categories = []
        total = 0
        for slug in TRASH_REGISTRY:
            model = get_model(slug)
            if model is None:
                continue
            count = deleted_queryset(model, gym).count()
            total += count
            categories.append({'slug': slug, 'count': count})
        return Response({'total': total, 'categories': categories})


class TrashListView(APIView):
    """GET /api/gyms/trash/<slug>/ — soft-deleted rows for one category."""

    permission_classes = [IsOwnerOrStaff]

    def get(self, request, slug):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        model = get_model(slug)
        if model is None:
            return Response({'detail': f'Unknown trash category "{slug}".'}, status=404)

        qs = deleted_queryset(model, gym).order_by('-deleted_at')

        search = request.query_params.get('search', '').strip()
        if search and hasattr(model, 'user'):
            from django.db.models import Q as _Q
            qs = qs.filter(
                _Q(user__first_name__icontains=search) | _Q(user__last_name__icontains=search) | _Q(user__email__icontains=search)
            )

        try:
            limit = min(int(request.query_params.get('limit', 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        serializer_cls = get_serializer_class(slug)
        rows = qs[:limit]
        data = []
        if serializer_cls is not None:
            for row in rows:
                item = serializer_cls(row, context={'request': request}).data
                item['deleted_at'] = row.deleted_at
                item['deleted_by_name'] = row.deleted_by.get_full_name() if row.deleted_by_id else ''
                data.append(item)
        else:
            for row in rows:
                data.append({
                    'id': row.pk,
                    'deleted_at': row.deleted_at,
                    'deleted_by_name': row.deleted_by.get_full_name() if row.deleted_by_id else '',
                    'label': str(row),
                })
        return Response({'count': qs.count(), 'results': data})


class TrashRestoreView(APIView):
    """POST /api/gyms/trash/<slug>/<id>/restore/ — bring one row back."""

    permission_classes = [IsOwnerOrStaff]

    def post(self, request, slug, pk):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        model = get_model(slug)
        if model is None:
            return Response({'detail': f'Unknown trash category "{slug}".'}, status=404)

        row = model.all_objects.filter(gym=gym, pk=pk).first()
        if row is None:
            return Response({'detail': 'Record not found in trash.'}, status=404)
        if not row.is_deleted:
            return Response({'detail': 'Record is not deleted.'}, status=400)

        conflict = self._restore_conflict(model, row)
        if conflict:
            return Response({'detail': conflict}, status=409)

        row.restore(user=request.user)
        # restore() only clears the soft-delete markers. Profile rows also
        # switched off their account when they were trashed, so let the model
        # undo that — otherwise a restored member comes back unable to log in.
        revive = getattr(row, 'revive', None)
        if callable(revive):
            revive()
        record_audit(
            gym=gym,
            actor=request.user,
            action=f'trash.restored.{slug}',
            request=request,
            target=row,
        )
        serializer_cls = get_serializer_class(slug)
        data = serializer_cls(row, context={'request': request}).data if serializer_cls else {'id': row.pk}
        return Response({'detail': 'Restored.', 'record': data})

    @staticmethod
    def _restore_conflict(model, row):
        """Detect uniqueness collisions that restoring would cause."""
        # Profile-style models: another live profile for the same user+gym.
        if hasattr(row, 'user_id') and getattr(row, 'gym_id', None):
            clash = (
                model.objects.filter(gym_id=row.gym_id, user_id=row.user_id)
                .exclude(pk=row.pk)
                .exists()
            )
            if clash:
                return 'A live record already exists for this user. Delete or merge it first, then restore.'
        # Membership plans / offers: unique name per gym.
        if hasattr(row, 'name') and getattr(row, 'gym_id', None):
            clash = (
                model.objects.filter(gym_id=row.gym_id, name=row.name)
                .exclude(pk=row.pk)
                .exists()
            )
            if clash:
                return f'A live record named "{row.name}" already exists. Rename or delete it first.'
        return None


class TrashPurgeView(APIView):
    """DELETE /api/gyms/trash/<slug>/<id>/ — permanently remove one row."""

    permission_classes = [IsOwnerOrStaff]

    def delete(self, request, slug, pk):
        gym = getattr(request, 'gym', None)
        if gym is None:
            return Response({'detail': 'An active gym membership is required.'}, status=400)
        model = get_model(slug)
        if model is None:
            return Response({'detail': f'Unknown trash category "{slug}".'}, status=404)

        row = model.all_objects.filter(gym=gym, pk=pk, deleted_at__isnull=False).first()
        if row is None:
            return Response({'detail': 'Record not found in trash.'}, status=404)

        label = str(row)
        record_audit(
            gym=gym,
            actor=request.user,
            action=f'trash.purged.{slug}',
            request=request,
            target=None,
            metadata={'model': model.__name__, 'pk': pk, 'label': label},
        )
        row.delete(hard=True)
        return Response({'detail': f'Permanently deleted: {label}.'})
