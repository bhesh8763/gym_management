#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# CLI subcommands that can wipe the target database.
FLUSH_COMMANDS = {'flush', 'sqlflush'}


def guard_flush_command(argv=None):
    """Refuse `flush`/`sqlflush` unless the target database name starts with test_.

    Bypass for intentional dev-DB wipes: set ALLOW_FLUSH=1.

    Only inspects command-line argv, so in-process calls such as Django's
    test runner invoking call_command('flush') on the test database are
    unaffected.
    """
    argv = sys.argv[1:] if argv is None else argv
    subcommand = next((arg for arg in argv if not arg.startswith('-')), None)
    if subcommand not in FLUSH_COMMANDS:
        return
    if os.environ.get('ALLOW_FLUSH') == '1':
        return

    alias = 'default'
    for i, arg in enumerate(argv):
        if arg == '--database' and i + 1 < len(argv):
            alias = argv[i + 1]
        elif arg.startswith('--database='):
            alias = arg.split('=', 1)[1]

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym_management.settings')
    from django.conf import settings
    db_name = str(settings.DATABASES.get(alias, {}).get('NAME') or '')

    if db_name.startswith('test_'):
        return

    sys.stderr.write(
        f"BLOCKED: 'manage.py {subcommand}' targets database "
        f"'{db_name or alias}' (alias '{alias}'), which is not a test_* "
        'database.\n'
        'Running it would wipe data in the development database.\n'
        'Allowed: databases whose name starts with "test_", or set '
        'ALLOW_FLUSH=1 to override deliberately.\n'
        'Ask the project owner before flushing anything.\n'
    )
    sys.exit(1)


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gym_management.settings')
    guard_flush_command()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
