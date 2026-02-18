"""Configuration module for testing batch edit priority."""

# Application settings
API_VERSION = "2.0"
DEBUG = False
MAX_RETRIES = 5

# Database settings
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "testdb"

# Feature flags
ENABLE_CACHE = True
ENABLE_LOGGING = True


def get_config():
    """Return current configuration."""
    return {
        "api_version": API_VERSION,
        "debug": DEBUG,
        "max_retries": MAX_RETRIES,
    }