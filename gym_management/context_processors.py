"""Template context shared by Django and django-allauth pages."""

from django.conf import settings


def deployment_context(request):
    """Expose the public frontend origin to server-rendered templates."""
    return {
        "FRONTEND_URL": settings.FRONTEND_URL.rstrip("/"),
    }
