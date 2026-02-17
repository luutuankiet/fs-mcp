"""Configuration module for testing batch edit priority."""

# Application settings
API_VERSION = "1.0"
DEBUG = True
MAX_RETRIES = 3

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