from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from stations.tasks import _read_excel_rows
from stations.services.import_pipeline import run_import

class Command(BaseCommand):
    help = "Run import from an Excel file"
    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to Excel file")

    def handle(self, *args, **options):
        file_path = options["file"]
        path = Path(file_path)

        if not path.exists():
            raise CommandError(f"File not found: {file_path}")

        rows = _read_excel_rows(str(path))
        result = run_import(rows, source_filename=path.name)
        self.stdout.write(self.style.SUCCESS(f"Import completed: {result}"))