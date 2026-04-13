from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal



class Truckstop(models.Model):
    opis_truckstop_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"


class Rack(models.Model):
    truckstop = models.ForeignKey(
        Truckstop,
        on_delete=models.CASCADE,
        related_name="racks"
    )
    rack_id = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["truckstop", "rack_id"],
                name="unique_rack_per_truckstop"
            )

        ]
    def __str__(self):
        return f"{self.rack_id} - {self.truckstop.name}"


class CurrentPrice(models.Model):
    rack = models.ForeignKey(
        Rack,
        on_delete=models.CASCADE,
        related_name="prices"
    )
    retail_price = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.00"))]
    )

    def __str__(self):
        return f"{self.retail_price} ({self.rack})"
    

class ImportJob(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    source_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)

    rows_total = models.IntegerField()
    rows_inserted = models.IntegerField()
    rows_deduped = models.IntegerField()
    rows_failed = models.IntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source_filename} ({self.status})"


class ImportIssue(models.Model):
    import_job = models.ForeignKey(
        ImportJob,
        on_delete=models.CASCADE,
        related_name="issues"
    )
    row_number = models.IntegerField()
    issue_type = models.CharField(max_length=100)
    message = models.TextField()
    raw_payload = models.JSONField()

    def __str__(self):
        return f"Issue at row {self.row_number}: {self.issue_type}"
