from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from stations.tasks import _read_rows
from stations.models import ImportJob
from stations.services.import_pipeline import run_import

class Command(BaseCommand):
    help = "Run import from a CSV or Excel file"
    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to CSV or Excel file")
        parser.add_argument(
            "--skip-if-imported",
            action="store_true",
            help="Skip the import when this source file was already imported successfully",
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        path = Path(file_path)

        if not path.exists():
            raise CommandError(f"File not found: {file_path}")

        if options["skip_if_imported"] and ImportJob.objects.filter(
            source_filename=path.name,
            status="completed",
        ).exists():
            self.stdout.write(f"Import skipped: {path.name} was already imported")
            return

        try:
            rows = _read_rows(str(path))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        result = run_import(rows, source_filename=path.name)
        self.stdout.write(self.style.SUCCESS(f"Import completed: {result}"))