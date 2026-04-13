from decimal import Decimal, InvalidOperation
import re

REQUIRED_HEADERS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]


def validate_headers(headers):
    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        raise ValueError(f"Missing headers: {', '.join(missing)}")


def normalize_row(row):
    normalized = {}

    for key in REQUIRED_HEADERS:
        value = row.get(key)

        if isinstance(value, str):
            value = value.strip()

            if key != "Retail Price":
                value = value.upper()

        normalized[key] = value

    return normalized


def parse_integer(value, field_name):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} is required")

    try:
        return int(str(value).strip())
    except ValueError:
        raise ValueError(f"{field_name} must be an integer")


def parse_price(value):
    if value is None:
        raise ValueError("Price must be numeric")

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    if value == "":
        raise ValueError("Price must be numeric")

    # Reject commas
    if "," in value:
        raise ValueError("Invalid price format")

    # Remove currency symbols like $
    value = re.sub(r"[^\d.\-]", "", value)

    # Reject malformed formats
    if value.count(".") > 1:
        raise ValueError("Invalid price format")

    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be numeric")

    if price <= 0:
        raise ValueError("Price must be positive")

    return price



def parse_rows(rows):
    valid_rows = []
    errors = []

    for index, row in enumerate(rows, start=1):
        try:
            # Normalize first
            normalized = normalize_row(row)

            # Validate required fields (not empty)
            for field in REQUIRED_HEADERS:
                if normalized.get(field) in [None, ""]:
                    raise ValueError(f"{field} is required")

            # Convert numeric fields
            normalized["OPIS Truckstop ID"] = parse_integer(
                normalized["OPIS Truckstop ID"],
                "OPIS Truckstop ID",
            )

            normalized["Rack ID"] = parse_integer(
                normalized["Rack ID"],
                "Rack ID",
            )

            # Parse price
            normalized["Retail Price"] = parse_price(
                normalized["Retail Price"]
            )

            valid_rows.append(normalized)

        except ValueError as e:
            errors.append({
                "row": index,
                "message": str(e),
            })

    return {
        "valid_rows": valid_rows,
        "errors": errors,
    }
