"""
Management command: backup_db

Creates a timestamped backup of the PostgreSQL database using pg_dump.
Saves backups to the project's backups/ directory.

Usage:
    python manage.py backup_db
    python manage.py backup_db --output /path/to/backup.sql
    python manage.py backup_db --compress
"""
import os
import subprocess
import sys
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Backup the PostgreSQL database using pg_dump.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', '-o',
            help='Output file path (default: backups/<db_name>_<timestamp>.sql)',
        )
        parser.add_argument(
            '--compress', '-c',
            action='store_true',
            help='Compress the backup with gzip',
        )
        parser.add_argument(
            '--schema',
            help='Only dump a specific schema (default: public)',
            default='public',
        )

    def handle(self, *args, **options):
        db_settings = settings.DATABASES['default']
        db_name = db_settings['NAME']
        db_user = db_settings['USER']
        db_host = db_settings['HOST']
        db_port = db_settings['PORT']

        # Create backups directory
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if options['output']:
            output_file = options['output']
        else:
            ext = '.sql.gz' if options['compress'] else '.sql'
            output_file = os.path.join(backup_dir, f'{db_name}_{timestamp}{ext}')

        # Build pg_dump command
        cmd = [
            'pg_dump',
            f'--host={db_host}',
            f'--port={db_port}',
            f'--username={db_user}',
            f'--schema={options["schema"]}',
            '--no-owner',
            '--no-acl',
        ]

        if options['compress']:
            cmd.append('--compress=9')

        cmd.extend(['--file=' + output_file, db_name])

        self.stdout.write(f'Backing up database "{db_name}" to {output_file}...')

        try:
            # Set PGPASSWORD so pg_dump doesn't prompt for a password
            env = os.environ.copy()
            env['PGPASSWORD'] = db_settings.get('PASSWORD', '')

            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                raise CommandError(f'pg_dump failed: {result.stderr}')

            file_size = os.path.getsize(output_file)
            size_mb = round(file_size / (1024 * 1024), 2)

            self.stdout.write(self.style.SUCCESS(
                f'Backup created: {output_file} ({size_mb} MB)'
            ))

        except FileNotFoundError:
            raise CommandError(
                'pg_dump not found. Install PostgreSQL client tools:\n'
                '  - Ubuntu/Debian: sudo apt install postgresql-client\n'
                '  - macOS: brew install postgresql\n'
                '  - Windows: Install from https://www.postgresql.org/download/windows/'
            )
        except subprocess.TimeoutExpired:
            raise CommandError('Backup timed out after 5 minutes.')
