
from django.db import migrations


def migrate_especialidad_forward(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')
    TecnicoEspecialidad = apps.get_model('accounts', 'TecnicoEspecialidad')

    tecnicos = CustomUser.objects.filter(role='TECNICO').exclude(especialidad='')
    for tecnico in tecnicos:
        TecnicoEspecialidad.objects.get_or_create(
            tecnico=tecnico,
            especialidad=tecnico.especialidad,
            defaults={'es_principal': True},
        )


def migrate_especialidad_backward(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_tecnico_especialidades_horario_programacion'),
    ]

    operations = [
        migrations.RunPython(
            migrate_especialidad_forward,
            migrate_especialidad_backward,
        ),
    ]
