"""Servicio de generación de reportes PDF para tickets resueltos.

Utiliza WeasyPrint para convertir un template HTML en un documento PDF
profesional que sirve como constancia de auditoría o garantía de servicio.

Genera dos variantes según el rol:
- **Residente**: Comprobante de garantía de servicio (sin historial de estados).
- **Admin**: Respaldo legal para auditoría (historial completo de estados).

Contenido del reporte:
- Encabezado del condominio (edificio, dirección, código)
- Información completa del ticket
- Autores involucrados (residente, técnico)
- Evidencias fotográficas del reporte y resolución
- Historial completo de estados (solo versión auditoría)
- Pie de página con marca de generación automática
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# En Windows, WeasyPrint requiere que las librerías GTK estén en el DLL search path.
# Agregamos la ruta de MSYS2 a los directorios de DLL seguros si existe.
if sys.platform == 'win32':
    gtk_path = r'C:\msys64\mingw64\bin'
    if os.path.isdir(gtk_path):
        os.add_dll_directory(gtk_path)

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


def _build_file_uri(file_path: Path) -> str:
    """Convierte un Path absoluto a una URI ``file:///`` válida para WeasyPrint.

    En Windows, ``Path.as_uri()`` produce ``file:///E:/path/to/file.jpg``
    que WeasyPrint reconoce correctamente para embeber imágenes locales.
    """
    try:
        return file_path.as_uri()
    except Exception:
        # Fallback: conversión manual con barras forward
        return 'file:///' + str(file_path).replace('\\', '/')


def generate_ticket_pdf(ticket: Ticket, *, is_audit: bool = False) -> bytes:
    """Genera el PDF del reporte de un ticket resuelto.

    Args:
        ticket: Instancia de Ticket con relaciones cargadas
                (inquilino, tecnico, unidad, unidad__edificio,
                 evidencias, historial__actor).
        is_audit: Si True, genera la versión completa de auditoría
                  (con historial de estados). Si False, genera un
                  comprobante de garantía de servicio para el residente.

    Returns:
        Bytes del documento PDF generado.
    """
    # Separar evidencias por momento
    evidencias = ticket.evidencias.select_related('subido_por').all()
    evidencias_reporte = []
    evidencias_resolucion = []

    for ev in evidencias:
        # Construir URI file:/// válida del archivo para que WeasyPrint lo embeba
        if ev.archivo:
            abs_path = Path(settings.MEDIA_ROOT) / str(ev.archivo)
            ev.archivo_uri = _build_file_uri(abs_path)
        else:
            ev.archivo_uri = None

        if ev.momento == 'REPORTE':
            evidencias_reporte.append(ev)
        else:
            evidencias_resolucion.append(ev)

    # Historial completo solo para versión auditoría
    historial = []
    if is_audit:
        historial = list(ticket.historial.select_related('actor').all())

    # Datos del edificio / condominio
    edificio = ticket.unidad.edificio
    unidad = ticket.unidad

    # Fecha/hora de generación del documento
    ahora = timezone.localtime(timezone.now())

    context = {
        'ticket': ticket,
        'edificio': edificio,
        'unidad': unidad,
        'inquilino': ticket.inquilino,
        'tecnico': ticket.tecnico,
        'evidencias_reporte': evidencias_reporte,
        'evidencias_resolucion': evidencias_resolucion,
        'historial': historial,
        'is_audit': is_audit,
        'fecha_generacion': ahora,
    }

    html_string = render_to_string('tickets/pdf/ticket_report.html', context)

    # Generar PDF con WeasyPrint
    # base_url apunta a MEDIA_ROOT para que rutas relativas se resuelvan
    html = HTML(
        string=html_string,
        base_url=str(settings.MEDIA_ROOT),
    )
    pdf_bytes = html.write_pdf()

    variant = "auditoría" if is_audit else "garantía"
    logger.info(
        "Reporte PDF (%s) generado para ticket %s (%d bytes)",
        variant, ticket.codigo, len(pdf_bytes),
    )

    return pdf_bytes
