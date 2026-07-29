
import apps.accounts.utils
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_migrate_especialidad_to_m2m'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='cedula',
            field=models.CharField(blank=True, help_text='Cédula ecuatoriana de 10 dígitos. Requerida para verificar la identidad del usuario.', max_length=10, null=True, unique=True, validators=[apps.accounts.utils.valida_cedula], verbose_name='Cédula de Identidad'),
        ),
        migrations.AlterField(
            model_name='customuser',
            name='phone',
            field=models.CharField(blank=True, max_length=20, null=True, validators=[django.core.validators.RegexValidator(message='Ingrese un número de teléfono válido (por ejemplo: 0991234567 o 042345678).', regex='^(0[2-9]\\d{7,8})$')], verbose_name='Teléfono'),
        ),
    ]
