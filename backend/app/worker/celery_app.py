from datetime import timedelta

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "fims",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.imports",
        "app.worker.tasks.catalog_import",
        "app.worker.tasks.video_search",
        "app.worker.tasks.reports",
        "app.worker.tasks.issuu_import",
        "app.worker.tasks.email_sync",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/New_York",
    enable_utc=True,
    task_routes={
        "app.worker.tasks.imports.*": {"queue": "imports"},
        "catalog_import.*": {"queue": "imports"},
        "video_search.*": {"queue": "imports"},
        "app.worker.tasks.reports.*": {"queue": "reports"},
        "app.worker.tasks.email_sync.*": {"queue": "imports"},
    },
    beat_schedule={
        "sync-email-accounts-every-15-minutes": {
            "task": "app.worker.tasks.email_sync.sync_email_accounts",
            "schedule": timedelta(minutes=15),
        },
    },
)
