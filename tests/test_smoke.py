import pytest
from django.conf import settings
from django.db import connection


@pytest.mark.django_db
def test_settings_module_loaded():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


@pytest.mark.django_db
def test_database_connection_works():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1;")
        result = cursor.fetchone()
    assert result[0] == 1

@pytest.mark.django_db
def test_tdd_red_step():
    assert 1 == 1