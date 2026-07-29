
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
    {
        'titulo': 'Inodoro que no deja de correr agua',
        'categoria': KnowledgeCategory.PLOMERIA,
        'contenido': """
        Si el inodoro sigue corriendo agua después de la descarga:
        1. Levanta la tapa del tanque y verifica si el flotador quedó atascado o el flapper
           (válvula de goma del fondo) no cierra bien.
        2. Mueve suavemente el flotador hacia abajo; si el agua se detiene, el ajuste es simple.
        3. Si el flapper está desgastado o no sella, cierra la llave de paso del inodoro
           (usualmente detrás o al lado de la base) para evitar desperdicio de agua.
        4. No dejes correr agua por más de unas horas — reporta la incidencia con foto del tanque abierto.
        Este problema no es una emergencia, pero sí conviene resolverlo pronto por el consumo de agua.
        """,
    },
    {
        'titulo': 'Baja presión de agua en todo el departamento',
        'categoria': KnowledgeCategory.PLOMERIA,
        'contenido': """
        Si la presión de agua bajó en todos los puntos de tu unidad (no solo un grifo):
        1. Verifica si es un problema general del edificio preguntando a un vecino o al administrador
           antes de reportar — puede ser mantenimiento programado de la cisterna o bomba.
        2. Revisa que la llave de paso general de tu unidad esté completamente abierta.
        3. Si el problema persiste solo en tu unidad, puede ser sedimento acumulado en aireadores
           de grifos — desenrósca la punta del grifo y límpiala.
        4. Si afecta a todo el edificio, repórtalo como incidencia de infraestructura compartida,
           no como plomería individual — así el administrador prioriza la revisión de la cisterna/bomba.
        """,
    },
    {
        'titulo': 'Parpadeo de luces o voltaje inestable',
        'categoria': KnowledgeCategory.ELECTRICIDAD,
        'contenido': """
        Si las luces parpadean o los electrodomésticos se reinician solos:
        1. Identifica si ocurre en todo el departamento o solo en un circuito/habitación.
        2. Desconecta electrodomésticos de alto consumo (aire acondicionado, microondas, secadora)
           uno por uno para ver si el parpadeo se detiene — puede indicar sobrecarga de un circuito.
        3. NO ignores parpadeos frecuentes ni olor a quemado en tomacorrientes — es señal de riesgo
           de cortocircuito o cableado dañado.
        4. Si el parpadeo afecta a varias unidades a la vez, probablemente es un problema de la
           acometida general del edificio, no de tu unidad — repórtalo como urgente igualmente.
        Un electricista certificado debe revisar cualquier parpadeo persistente o con olor a quemado.
        """,
    },
    {
        'titulo': 'Persona sospechosa o acceso no autorizado',
        'categoria': KnowledgeCategory.SEGURIDAD,
        'contenido': """
        Si detectas a alguien sospechoso intentando ingresar al edificio o merodeando:
        1. No confrontes directamente a la persona — mantén distancia y observa desde un lugar seguro.
        2. Avisa de inmediato al guardia de seguridad o a la administración por el canal más rápido
           disponible (interfono, WhatsApp de guardia, llamada).
        3. Si hay forcejeo, intento de robo o violencia en curso, llama al 911 primero.
        4. Reporta el incidente en InmoHelpdesk con la hora aproximada y descripción, incluso si
           ya se resolvió, para que quede registro y se revisen cámaras si el edificio las tiene.
        La seguridad de personas siempre tiene prioridad sobre el reporte formal — repórtalo después.
        """,
    },
    {
        'titulo': 'Ascensor detenido o con fallas',
        'categoria': KnowledgeCategory.INFRAESTRUCTURA,
        'contenido': """
        Si el ascensor se detiene entre pisos o no responde:
        1. Si hay personas atrapadas, usa el botón de alarma/intercomunicador del ascensor —
           tiene línea directa con seguridad o mantenimiento en la mayoría de edificios.
        2. No intentes forzar las puertas ni salir por tu cuenta si estás atrapado — espera asistencia.
        3. Si el ascensor solo hace ruido raro, se detiene bruscamente o no nivela bien con el piso
           (sin que nadie quede atrapado), repórtalo igual como incidencia de infraestructura antes
           de que empeore.
        4. Mientras se repara, usa las escaleras y avisa a vecinos con movilidad reducida del corte
           de servicio.
        Cualquier falla de ascensor es prioridad alta — afecta a todo el edificio, no solo a ti.
        """,
    },
    {
        'titulo': 'Grietas o desprendimientos en paredes y techos comunes',
        'categoria': KnowledgeCategory.INFRAESTRUCTURA,
        'contenido': """
        Ante grietas, desprendimiento de pintura o caída de material en zonas comunes (pasillos,
        parqueadero, fachada):
        1. Aleja objetos y personas de la zona si hay riesgo de caída de material.
        2. Documenta con fotos amplias (mostrando el contexto, no solo el detalle) y, si puedes,
           una referencia de tamaño (moneda, mano) para dimensionar el daño.
        3. Grietas pequeñas y estables (que no crecen) son de prioridad media; grietas que crecen,
           cielo raso que cede, o desprendimiento activo de material son urgentes.
        4. No intentes sellar o reparar zonas comunes por cuenta propia — es responsabilidad del
           administrador coordinar la evaluación estructural si aplica.
        """,
    },
    {
        'titulo': 'Plagas — cucarachas, roedores u otros insectos',
        'categoria': KnowledgeCategory.LIMPIEZA,
        'contenido': """
        Ante presencia de plagas en tu unidad o áreas comunes:
        1. Identifica si es un caso aislado en tu unidad o si vecinos reportan lo mismo — esto
           determina si se necesita fumigación puntual o general del edificio.
        2. Mientras se coordina la fumigación: sella alimentos, tapa desagües sin uso y evita dejar
           basura acumulada, que atrae más plagas.
        3. No apliques insecticidas caseros en exceso en áreas comunes — puede interferir con la
           fumigación profesional programada.
        4. Reporta indicando ubicación exacta, tipo de plaga y si es recurrente (ya reportado antes).
        Las plagas no son una emergencia de seguridad, pero si son recurrentes ameritan prioridad alta
        por el impacto en salubridad de varias unidades.
        """,
    },
    {
        'titulo': 'Limpieza de áreas comunes — horarios y responsabilidades',
        'categoria': KnowledgeCategory.LIMPIEZA,
        'contenido': """
        Sobre la limpieza de zonas comunes del edificio:
        1. El personal de limpieza contratado por la administración cubre pasillos, lobby, escaleras
           y áreas sociales según el horario publicado en la cartelera o app del edificio.
        2. La limpieza dentro de tu unidad es responsabilidad del residente — no está incluida.
        3. Si notas que un área común lleva varios días sin limpiar o hay un derrame que requiere
           atención inmediata (no puede esperar al horario regular), repórtalo como incidencia.
        4. Derrames de líquidos en pasillos o escaleras son prioridad alta por riesgo de caídas,
           independientemente del horario regular de limpieza.
        """,
    },
    {
        'titulo': 'Uso y reserva de áreas comunes (salón social, gimnasio, terraza)',
        'categoria': KnowledgeCategory.REGLAMENTO,
        'contenido': """
        Reglas generales para el uso de áreas sociales del edificio:
        1. Las reservas de salón social/terraza se solicitan a la administración con al menos 48
           horas de anticipación, sujetas a disponibilidad y al reglamento interno.
        2. El gimnasio y áreas de ejercicio tienen horario limitado (usualmente 06:00–22:00) y
           requieren mantener el orden y limpieza básica después de su uso.
        3. Daños a mobiliario o equipos de áreas comunes durante un evento reservado son
           responsabilidad del residente que hizo la reserva.
        4. El uso de estas áreas no requiere ticket de mantenimiento salvo que haya un daño físico
           o falla de equipo que reportar.
        """,
    },
    {
        'titulo': 'Contacto de guardia 24h y protocolo de emergencias del edificio',
        'categoria': KnowledgeCategory.REGLAMENTO,
        'contenido': """
        El edificio cuenta con guardia de seguridad las 24 horas en la portería principal.
        1. Para emergencias que requieren acción inmediata (persona sospechosa, incendio, alguien
           atrapado en el ascensor), contacta primero al guardia por el intercomunicador de tu unidad
           o la línea directa publicada en la cartelera.
        2. El guardia puede escalar a la administración o a servicios de emergencia (911, bomberos)
           según el caso.
        3. Para incidencias de mantenimiento que no son emergencia, usa siempre InmoHelpdesk en vez
           de pedirle al guardia que gestione el reporte — así queda con seguimiento formal.
        4. El guardia no está autorizado a ingresar a tu unidad sin tu presencia o autorización
           expresa, salvo emergencia con riesgo para el edificio.
        """,
    },
    {
        'titulo': 'Política de mascotas en el edificio',
        'categoria': KnowledgeCategory.GENERAL,
        'contenido': """
        Sobre la tenencia de mascotas en el edificio:
        1. Las mascotas deben transitar por áreas comunes (pasillos, ascensor, lobby) con correa
           y, en el caso de perros, con bozal si el reglamento interno del edificio lo exige.
        2. El propietario es responsable de recoger inmediatamente los desechos de su mascota en
           áreas comunes.
        3. Ruido excesivo o ladridos prolongados que afecten a vecinos pueden reportarse como
           incidencia de convivencia, no como mantenimiento.
        4. Daños causados por mascotas a áreas comunes (arañazos en puertas de ascensor, jardines)
           son responsabilidad del propietario de la mascota.
        """,
    },
    {
        'titulo': 'Parqueadero de visitas — normas y horarios',
        'categoria': KnowledgeCategory.GENERAL,
        'contenido': """
        Sobre el uso del parqueadero de visitas:
        1. Los espacios de visitas son de uso temporal (máximo 24 horas salvo autorización de
           administración) y no pueden usarse como parqueadero fijo adicional de un residente.
        2. Todo vehículo de visita debe registrarse con el guardia indicando placa, unidad que
           visita y hora aproximada de salida.
        3. Vehículos mal estacionados que bloqueen circulación pueden reportarse a la administración
           para que se contacte al propietario.
        4. Daños a vehículos en el parqueadero (de residentes o visitas) deben reportarse de
           inmediato para revisión de cámaras de seguridad, si el edificio cuenta con ellas.
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
