
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('properties', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='unidad',
            name='inquilino',
            field=models.OneToOneField(blank=True, limit_choices_to={'role': 'INQUILINO'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='unidad_asignada', to=settings.AUTH_USER_MODEL, verbose_name='Residente asignado'),
        ),
    ]
