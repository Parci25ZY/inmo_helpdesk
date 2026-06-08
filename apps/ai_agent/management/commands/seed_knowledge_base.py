"""Comando para poblar la base de conocimiento RAG con FAQs de mantenimiento."""

from django.core.management.base import BaseCommand

from apps.ai_agent.models import KnowledgeCategory, KnowledgeDocument
from apps.ai_agent.tasks import index_knowledge_document

SEED_DOCUMENTS = [
    {
        'titulo': 'Cierre de llave de paso de agua',
        'categoria': KnowledgeCategory.PLOMERIA,
        'contenido': """
        Para cerrar la llave de paso de agua en un departamento típico:
        1. Localiza la llave de paso general, usualmente bajo el lavamanos del baño principal
           o en la cocina, cerca de la conexión de la lavadora.
        2. Gira la perilla en sentido horario (derecha) hasta que deje de girar con resistencia.
        3. Si es una palanca tipo mariposa, gírala 90 grados para que quede perpendicular a la tubería.
        4. Abre un grifo para verificar que el flujo se detuvo.
        En caso de fuga activa y no poder cerrar la llave, contacta inmediatamente al administrador
        o reporta una incidencia urgente.
        """,
    },
    {
        'titulo': 'Fuga de agua leve en grifo o lavamanos',
        'categoria': KnowledgeCategory.PLOMERIA,
        'contenido': """
        Si detectas una fuga leve en un grifo:
        1. Coloca un recipiente bajo la gotera para evitar daños.
        2. Cierra la llave de paso local de ese punto de agua si es posible.
        3. No fuerces la perilla del grifo; puede empeorar el sellado.
        4. Seca el área para evitar humedad y moho.
        5. Reporta la incidencia en InmoHelpdesk con foto si es posible.
        Las fugas persistentes requieren un plomero — no intentes desarmar la mezcladora
        sin experiencia.
        """,
    },
    {
        'titulo': 'Disyuntor saltado — restablecer energía',
        'categoria': KnowledgeCategory.ELECTRICIDAD,
        'contenido': """
        Si se fue la luz solo en tu departamento:
        1. Identifica el tablero eléctrico (breakers) dentro de tu unidad o en el pasillo técnico.
        2. Busca el interruptor en posición intermedia o apagado (generalmente hacia abajo).
        3. Primero apágalo completamente y luego enciéndelo firmemente hacia arriba.
        4. Si salta de nuevo inmediatamente, NO lo insistas — puede haber un cortocircuito.
        5. Desconecta electrodomésticos recién conectados y reporta la incidencia.
        Nunca manipules el medidor principal ni cableado expuesto. Eso requiere un electricista certificado.
        """,
    },
    {
        'titulo': 'Horario de visitas técnicas',
        'categoria': KnowledgeCategory.REGLAMENTO,
        'contenido': """
        Las visitas de mantenimiento programadas se realizan de lunes a viernes entre 08:00 y 17:00,
        y los sábados de 08:00 a 12:00. Para emergencias fuera de horario (inundación, gas, cortocircuito
        con chispas), el administrador activa guardia según el reglamento interno del edificio.
        El técnico coordinará contigo la hora exacta una vez el ticket esté en estado ASIGNADO.
        """,
    },
    {
        'titulo': 'Procedimiento de reporte de incidencias',
        'categoria': KnowledgeCategory.REGLAMENTO,
        'contenido': """
        Para reportar un problema de mantenimiento en InmoHelpdesk:
        1. Describe el problema con el mayor detalle posible (ubicación, cuándo empezó, si empeora).
        2. Adjunta fotos claras del daño o avería.
        3. Indica si hay riesgo inmediato para personas o bienes.
        4. El sistema clasificará la prioridad y un administrador validará la asignación del técnico.
        5. Puedes seguir el estado del ticket en tu bandeja personal.
        """,
    },
    {
        'titulo': 'Filtración en techo o pared por lluvia',
        'categoria': KnowledgeCategory.GENERAL,
        'contenido': """
        Ante filtraciones por lluvia:
        1. Protege muebles y equipos con plástico o toallas.
        2. Coloca un balde si hay goteo activo.
        3. No perforar ni aplicar selladores por cuenta propia en fachada o losa.
        4. Documenta con fotos y reporta de inmediato — puede ser problema estructural o de impermeabilización.
        5. Si hay riesgo de derrumbe de cielo raso, evacúa la zona y reporta como urgente.
        """,
    },
    {
        'titulo': 'Emergencias — gas, incendio, inundación grave',
        'categoria': KnowledgeCategory.SEGURIDAD,
        'contenido': """
        EMERGENCIAS — actúa en este orden:
        GAS: No enciendas luces ni electrodomésticos. Abre ventanas, evacúa, cierra la válvula de gas
        si sabes dónde está y es seguro hacerlo. Llama al 911.
        INCENDIO: Evacúa, usa extintor solo si el fuego es muy pequeño. Llama al 911. No uses ascensor.
        INUNDACIÓN GRAVE: Cierra llave de paso general, desconecta equipos eléctricos si no hay riesgo.
        Reporta inmediatamente en InmoHelpdesk marcando prioridad crítica.
        """,
    },
]


class Command(BaseCommand):
    help = 'Carga documentos FAQ iniciales y los indexa para RAG.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reindexa documentos existentes con el mismo título.',
        )

    def handle(self, *args, **options):
        created = 0
        indexed = 0

        for data in SEED_DOCUMENTS:
            doc, was_created = KnowledgeDocument.objects.get_or_create(
                titulo=data['titulo'],
                defaults={
                    'categoria': data['categoria'],
                    'contenido': data['contenido'].strip(),
                    'activo': True,
                },
            )
            if was_created:
                created += 1
            elif options['force']:
                doc.contenido = data['contenido'].strip()
                doc.categoria = data['categoria']
                doc.indexado = False
                doc.save()

            if not doc.indexado or options['force']:
                try:
                    index_knowledge_document.delay(doc.pk)
                except Exception:
                    from apps.ai_agent.services.rag import index_document
                    index_document(doc)
                indexed += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Listo: {created} documento(s) nuevos, {indexed} en cola/indexados.'
            )
        )
