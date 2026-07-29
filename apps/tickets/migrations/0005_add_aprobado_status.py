
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0004_tecnico_especialidades_horario_programacion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='historialestado',
            name='estado_anterior',
            field=models.CharField(blank=True, choices=[('CREADO_PENDIENTE_IA', 'Creado · Pendiente IA'), ('ANALIZADO_POR_IA', 'Analizado por IA'), ('PENDIENTE_VALIDACION', 'Pendiente Validación'), ('APROBADO', 'Aprobado · Pendiente Agenda'), ('ASIGNADO', 'Asignado'), ('EN_CAMINO', 'En Camino'), ('EN_PROGRESO', 'En Progreso'), ('RESUELTO', 'Resuelto'), ('CANCELADO', 'Cancelado')], max_length=30, verbose_name='Estado anterior'),
        ),
        migrations.AlterField(
            model_name='historialestado',
            name='estado_nuevo',
            field=models.CharField(choices=[('CREADO_PENDIENTE_IA', 'Creado · Pendiente IA'), ('ANALIZADO_POR_IA', 'Analizado por IA'), ('PENDIENTE_VALIDACION', 'Pendiente Validación'), ('APROBADO', 'Aprobado · Pendiente Agenda'), ('ASIGNADO', 'Asignado'), ('EN_CAMINO', 'En Camino'), ('EN_PROGRESO', 'En Progreso'), ('RESUELTO', 'Resuelto'), ('CANCELADO', 'Cancelado')], max_length=30, verbose_name='Estado nuevo'),
        ),
        migrations.AlterField(
            model_name='ticket',
            name='estado',
            field=models.CharField(choices=[('CREADO_PENDIENTE_IA', 'Creado · Pendiente IA'), ('ANALIZADO_POR_IA', 'Analizado por IA'), ('PENDIENTE_VALIDACION', 'Pendiente Validación'), ('APROBADO', 'Aprobado · Pendiente Agenda'), ('ASIGNADO', 'Asignado'), ('EN_CAMINO', 'En Camino'), ('EN_PROGRESO', 'En Progreso'), ('RESUELTO', 'Resuelto'), ('CANCELADO', 'Cancelado')], default='CREADO_PENDIENTE_IA', max_length=30, verbose_name='Estado'),
        ),
    ]
