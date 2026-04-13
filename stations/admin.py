from django.contrib import admin
from .models import Truckstop, Rack, CurrentPrice, ImportJob, ImportIssue 


# Inline for prices inside Rack
class CurrentPriceInline(admin.TabularInline):
    model = CurrentPrice
    extra = 0


class RackInline(admin.TabularInline):
    model = Rack
    extra = 0


@admin.register(Truckstop)
class TruckstopAdmin(admin.ModelAdmin):
    list_display = ("opis_truckstop_id", "name", "city", "state")
    
    # Search requirement
    search_fields = (
        "opis_truckstop_id",
        "name",
        "city",
        "state",
    )

    inlines = [RackInline]


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ("rack_id", "truckstop")
    search_fields = ("rack_id", "truckstop__name")

    inlines = [CurrentPriceInline]


@admin.register(CurrentPrice)
class CurrentPriceAdmin(admin.ModelAdmin):
    list_display = ("rack", "retail_price", "updated_at", "updated_by")

    # Allow editing
    list_editable = ("retail_price",)

    def save_model(self, request, obj, form, change):
        # Track who edited
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = (
        "source_filename",
        "status",
        "rows_total",
        "rows_inserted",
        "rows_failed",
        "rows_deduped",
        "created_at",
    )


@admin.register(ImportIssue)
class ImportIssueAdmin(admin.ModelAdmin):
    list_display = ("import_job", "row_number", "issue_type")
    search_fields = ("message",)
