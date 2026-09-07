"""
Management command: ensure_site

Creates the django.contrib.sites.Site(id=1) object required by django-allauth.
Run once after migrations. Safe to run repeatedly (idempotent).

Usage:
    python manage.py ensure_site
    python manage.py ensure_site --domain example.com --name "FitCore"
"""
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Ensure the allauth Site(id=1) object exists.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain',
            default='localhost',
            help='Site domain (default: localhost)',
        )
        parser.add_argument(
            '--name',
            default='FitCore',
            help='Site display name (default: FitCore)',
        )

    def handle(self, *args, **options):
        site, created = Site.objects.get_or_create(
            id=settings.SITE_ID,
            defaults={
                'domain': options['domain'],
                'name': options['name'],
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Created Site(id={site.id}): domain={site.domain}, name={site.name}'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'Site(id={site.id}) already exists: domain={site.domain}, name={site.name}'
            ))
