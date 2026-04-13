from collections import OrderedDict


def build_duplicate_key(row):
    """
    Build a unique identity key for a row using all identity fields.
    """
    return (
        row["OPIS Truckstop ID"],
        row["Address"],
        row["City"],
        row["State"],
        row["Rack ID"],
    )


def collapse_duplicates_keep_highest(rows):
    """
    Deduplicate rows based on identity fields.
    
    Rules:
    - Keep one row per unique key
    - If duplicates exist → keep the one with highest Retail Price
    - If same price → keep first seen (deterministic)
    """
    deduped = OrderedDict()
    duplicates_removed = 0

    for row in rows:
        key = build_duplicate_key(row)

        if key not in deduped:
            deduped[key] = row
            continue

        # Duplicate found
        existing = deduped[key]

        # Compare prices
        if row["Retail Price"] > existing["Retail Price"]:
            deduped[key] = row  # replace with higher price

        # If equal → keep first (do nothing)

        duplicates_removed += 1

    return {
        "rows": list(deduped.values()),
        "duplicates_removed": duplicates_removed,
    }
