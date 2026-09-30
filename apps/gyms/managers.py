from asgiref.local import Local
from django.db import models
from django.db.models import Q

# Request-local tenant context. It is intentionally not a process-global
# variable, so concurrent ASGI requests cannot leak a gym into one another.
tenant_context = Local()


class TenantManager(models.Manager):
    """Automatically scope tenant-owned models to the current request gym.

    Soft-deleted rows (``deleted_at`` set) are hidden from every default
    lookup. Use ``all_objects`` to reach them (trash listing / restore) and
    ``base_objects`` for raw FK traversal, which must keep seeing deleted
    rows so financial history stays readable.
    """

    def __init__(self, *args, include_deleted=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.include_deleted = include_deleted

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.include_deleted and getattr(queryset.model, 'deleted_at', None) is not None:
            queryset = queryset.filter(deleted_at__isnull=True)
        try:
            gym = tenant_context.gym
        except AttributeError:
            gym = None
        if gym is not None:
            queryset = queryset.filter(gym=gym)
        try:
            branch = tenant_context.branch
        except AttributeError:
            branch = None
        if branch is not None:
            queryset = queryset.filter(Q(branch=branch) | Q(branch__isnull=True))
        return queryset
