
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_agent', '0002_alter_knowledgechunk_embedding'),
    ]

    operations = [
        migrations.AlterField(
            model_name='knowledgedocument',
            name='categoria',
            field=models.CharField(choices=[('PLOMERIA', 'Plomería'), ('ELECTRICIDAD', 'Electricidad'), ('INFRAESTRUCTURA', 'Infraestructura'), ('LIMPIEZA', 'Limpieza'), ('SEGURIDAD', 'Seguridad'), ('REGLAMENTO', 'Reglamento'), ('GENERAL', 'General')], default='GENERAL', max_length=20, verbose_name='Categoría'),
        ),
    ]
