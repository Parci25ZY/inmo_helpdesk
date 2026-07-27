import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('inmo_helpdesk')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
# apps/tickets/notifications.py define @shared_task pero no se llama
# `tasks.py` — autodiscover_tasks() con su related_name por defecto ('tasks')
# nunca lo importa, así que el worker real nunca registraba
# notify_nuevo_ticket (silenciosamente descartado como "unregistered task").
app.autodiscover_tasks(related_name='notifications')
