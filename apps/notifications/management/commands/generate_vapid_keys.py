"""
Generate a VAPID keypair for Web Push (PWA notifications).

Usage:
    python manage.py generate_vapid_keys

Prints two environment variables to paste into .env (local) and into
Render's environment tab (production). The keys are generated with the
same cryptography/py-vapid libraries pywebpush uses, and are validated
against pywebpush's parser before printing.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate a VAPID keypair for Web Push (paste the output into .env / Render env vars)'

    def handle(self, *args, **options):
        # Imported here so a missing py-vapid fails with a clear message.
        from py_vapid import Vapid01

        private_key = ec.generate_private_key(ec.SECP256R1())
        private_der = private_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        public_bytes = private_key.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        private_b64 = base64.urlsafe_b64encode(private_der).decode().rstrip('=')
        public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip('=')

        # Fail loudly if pywebpush cannot parse what we generated.
        Vapid01.from_string(private_b64)

        self.stdout.write(self.style.SUCCESS('VAPID keypair generated.\n'))
        self.stdout.write('Add these to .env (local) and to Render > Environment (production):\n')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'VAPID_PUBLIC_KEY={public_b64}'))
        self.stdout.write(self.style.WARNING(f'VAPID_PRIVATE_KEY={private_b64}'))
        self.stdout.write('# Contact mailbox/URL required by the push protocol:')
        self.stdout.write('VAPID_SUBJECT=mailto:you@example.com')
        self.stdout.write('')
        self.stdout.write('Keep VAPID_PRIVATE_KEY secret. Changing the keys invalidates')
        self.stdout.write('existing subscriptions — users just re-subscribe on next login.')
