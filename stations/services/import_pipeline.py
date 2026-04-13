from django.db import transaction

from stations.models import (
    Truckstop,
    Rack,
    CurrentPrice,
    ImportJob,
    ImportIssue,
)

from stations.services.parsing import parse_rows
from stations.services.deduplication import collapse_duplicates_keep_highest


def run_import(rows, source_filename: str):
    # Step 1: Parse
    parsed = parse_rows(rows)
    valid_rows = parsed["valid_rows"]
    errors = parsed["errors"]

    # Step 2: Deduplicate
    deduped = collapse_duplicates_keep_highest(valid_rows)
    final_rows = deduped["rows"]
    duplicates_removed = deduped["duplicates_removed"]

    # Step 3: Create ImportJob
    job = ImportJob.objects.create(
        source_filename=source_filename,
        status="pending",
        rows_total=len(rows),
        rows_inserted=0,
        rows_deduped=duplicates_removed,
        rows_failed=len(errors),
    )

    inserted_count = 0

    try:
        with transaction.atomic():
            # Step 4: Persist valid rows
            for row in final_rows:
                truckstop, _ = Truckstop.objects.get_or_create(
                    opis_truckstop_id=int(row["OPIS Truckstop ID"]),
                    defaults={
                        "name": row["Truckstop Name"],
                        "address": row["Address"],
                        "city": row["City"],
                        "state": row["State"],
                    },
                )

                rack, _ = Rack.objects.get_or_create(
                    truckstop=truckstop,
                    rack_id=int(row["Rack ID"]),
                )

                CurrentPrice.objects.create(
                    rack=rack,
                    retail_price=row["Retail Price"],
                )

                inserted_count += 1

            # Step 5: Save ImportIssues
            for error in errors:
                ImportIssue.objects.create(
                    import_job=job,
                    row_number=error["row"],
                    issue_type="parse_error",
                    message=error["message"],
                    raw_payload={},
                )

            # Step 6: Update job success
            job.rows_inserted = inserted_count
            job.status = "completed"
            job.save()

    except Exception:
        # Step 7: rollback handled automatically
        # mark job as failed
        job.status = "failed"
        job.save()
        raise

    return {
        "job_id": job.id,
        "rows_total": len(rows),
        "rows_inserted": inserted_count,
        "rows_failed": len(errors),
        "rows_deduped": duplicates_removed,
    }
