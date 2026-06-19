from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MensajeTicket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mensaje', models.TextField(max_length=1000, verbose_name='Mensaje')),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('autor', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='mensajes_ticket',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('ticket', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='mensajes',
                    to='tickets.ticket',
                )),
            ],
            options={
                'verbose_name': 'Mensaje',
                'verbose_name_plural': 'Mensajes',
                'ordering': ['creado_en'],
            },
        ),
    ]
