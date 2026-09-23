"""
Bulk data import endpoints (Owner only).

    GET  /api/import/           → supported sheets, columns and limits (for the UI)
    GET  /api/import/template/  → downloadable .xlsx template workbook
    POST /api/import/           → validate (dry_run=true, default) or commit the file

POST accepts multipart form data:
    file             — the .xlsx workbook
    dry_run          — 'true' (preview only, no writes) or 'false' (import)
    default_password — optional shared password for created accounts
"""
from django.http import HttpResponse
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOwner

from .importer import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_ROWS_PER_SHEET,
    run_import,
)
from .schema import SHEETS
from .template import build_template_bytes

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class ImportView(APIView):
    """GET the import schema, POST a workbook to preview or commit it."""

    permission_classes = [IsOwner]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response({
            'sheets': [
                {
                    'key': sheet.key,
                    'name': sheet.name,
                    'description': sheet.description,
                    'columns': [
                        {'label': column.label, 'required': column.required}
                        for column in sheet.columns
                    ],
                }
                for sheet in SHEETS
            ],
            'limits': {
                'max_file_bytes': MAX_FILE_BYTES,
                'max_rows_per_sheet': MAX_ROWS_PER_SHEET,
                'allowed_extensions': list(ALLOWED_EXTENSIONS),
            },
        })

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            return Response(
                {'error': 'Choose an Excel (.xlsx) file to import.'},
                status=400,
            )

        filename = (upload.name or '').lower()
        if not filename.endswith(ALLOWED_EXTENSIONS):
            return Response(
                {'error': 'Only Excel .xlsx workbooks are supported — download the '
                          'template to get the right format.'},
                status=400,
            )
        if upload.size and upload.size > MAX_FILE_BYTES:
            return Response(
                {'error': f'File is too large ({upload.size // 1024:,} KB). '
                          f'The maximum is {MAX_FILE_BYTES // 1000:,} KB — split it up.'},
                status=400,
            )

        dry_run = str(request.data.get('dry_run', 'true')).lower() in ('1', 'true', 'yes', 'on')
        password = (request.data.get('default_password') or '').strip() or None
        if password and len(password) < 6:
            return Response(
                {'error': 'The default password must be at least 6 characters.'},
                status=400,
            )

        report = run_import(
            upload,
            actor=request.user,
            dry_run=dry_run,
            default_password=password,
        )
        if report['error']:
            return Response(report, status=400)
        if not dry_run and not report['ok']:
            return Response(report, status=400)
        return Response(report)


class ImportTemplateView(APIView):
    """Download the fill-in template workbook."""

    permission_classes = [IsOwner]

    def get(self, request):
        response = HttpResponse(build_template_bytes(), content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = 'attachment; filename="fitcore_import_template.xlsx"'
        return response
