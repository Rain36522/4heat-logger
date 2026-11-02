"""Django settings for the heating monitor.

Everything that differs between machines comes from environment variables
(see README.md for the list), so the same image runs anywhere.
"""

import os
import secrets
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# Folder holding the SQLite file and the generated secret key (a volume in Docker).
DB_DIR = Path(os.environ.get("DJANGO_DB_DIR", BASE_DIR / "db"))
DB_DIR.mkdir(parents=True, exist_ok=True)


def _load_secret_key() -> str:
    """DJANGO_SECRET_KEY if set, otherwise a key generated once and kept in DB_DIR."""
    key = os.environ.get("DJANGO_SECRET_KEY")
    if key:
        return key
    key_file = DB_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_urlsafe(50)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key


SECRET_KEY = _load_secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "") == "1"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "monitor",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page needs a login, except the ones marked login_not_required (the login page).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# SQLite by default. DATABASE_URL (e.g. postgres://user:password@host/dbname) switches to
# another database; use a database created for this app, never another application's.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=60)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DB_DIR / "db.sqlite3",
            "OPTIONS": {"timeout": 20},  # the web and telegram-com containers share this file
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "status"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "fr"
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
# The 4HEAT logger writes naive local times, so the whole app works in naive local time
# too: journal entries and CSV readings are directly comparable.
USE_TZ = False

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Heating monitor ---------------------------------------------------------------
# CSV written by the 4HEAT logger (read-only for this app).
HEATING_CSV_PATH = os.environ.get("HEATING_CSV_PATH", str(BASE_DIR / "data" / "4heat_log.csv"))
# The status page says "running" when the last reading is younger than this.
STATUS_LIVE_MAX_AGE_S = 180
# Telegram alerts (python manage.py run_alerts). Both must be set to enable them.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
