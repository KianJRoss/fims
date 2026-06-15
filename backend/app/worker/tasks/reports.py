from app.worker.celery_app import celery_app


@celery_app.task(name="app.worker.tasks.reports.daily_summary")
def daily_summary():
    """Nightly: compute best sellers, margin summary, write to a report table."""
    pass  # implement when reporting module is built
