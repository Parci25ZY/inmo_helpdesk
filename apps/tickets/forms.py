"""Formularios del módulo Tickets.

Cada formulario está pensado para un rol/contexto específico:

* :class:`TicketCreateForm` — el residente reporta un nuevo ticket.
* :class:`TicketAdminValidateForm` — el administrador valida la sugerencia
  IA y asigna técnico (transición PENDIENTE_VALIDACION → ASIGNADO).
* :class:`TicketTransitionForm` — wrapper genérico para añadir notas a
  cualquier transición de estado.
* :class:`MensajeForm` — mensaje en el hilo de comunicación técnico ↔ residente.
"""

from __future__ import annotations

from django import forms

from apps.accounts.models import CustomUser
from apps.properties.models import Unidad

from .models import MensajeTicket, Ticket, TicketCategory, TicketPriority

INPUT_CLASS = (
    'w-full bg-transparent border-0 border-b-2 border-zinc-200 py-3 px-0 '
    'text-base font-medium text-zinc-900 placeholder-zinc-300 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
SELECT_CLASS = (
    'w-full bg-white border border-zinc-200 rounded py-3 px-3 '
    'text-base font-medium text-zinc-900 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
TEXTAREA_CLASS = INPUT_CLASS + ' min-h-[140px] resize-y'


class TicketCreateForm(forms.ModelForm):
    """Formulario público para creación de tickets por parte del residente."""

    def __init__(self, *args, inquilino=None, **kwargs):
        super().__init__(*args, **kwargs)
        if inquilino is not None:
            unidad = getattr(inquilino, 'unidad_asignada', None)
            if unidad is not None:
                self.fields['unidad'].queryset = Unidad.objects.filter(pk=unidad.pk)
                self.fields['unidad'].initial = unidad.pk
            else:
                self.fields['unidad'].queryset = Unidad.objects.none()

    class Meta:
        model = Ticket
        fields = ['unidad', 'titulo', 'descripcion']
        widgets = {
            'unidad': forms.Select(attrs={'class': SELECT_CLASS}),
            'titulo': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Ej. Fuga de agua en cocina',
                'maxlength': 200,
            }),
            'descripcion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'placeholder': 'Describe con detalle qué ocurre, dónde y cuándo empezó.',
                'rows': 5,
            }),
        }


class TicketAdminValidateForm(forms.ModelForm):
    """Formulario que usa el administrador para aprobar el ticket.

    El administrador puede:
      * Ajustar categoría / prioridad si discrepa con la IA.
      * Asignar el técnico definitivo (puede aceptar el sugerido).
      * Ver la carga de trabajo y disponibilidad de cada técnico.

    Los técnicos sin capacidad aparecen en un optgroup separado con sus
    opciones deshabilitadas, evitando selecciones que luego fallarán al
    agendar (WorkloadExceededError).

    Ya NO programa fecha/hora. Eso lo hace el inquilino en el paso siguiente.

    Nota de implementación: usamos TypedChoiceField (en lugar de ModelChoiceField)
    porque ModelChoiceField ignora los choices asignados manualmente — siempre
    itera su queryset. TypedChoiceField respeta la lista de choices y coerce=int
    convierte el PK. clean_tecnico() resuelve el PK al objeto CustomUser.
    """

    # Campo declarado explícitamente como TypedChoiceField para respetar
    # los choices con optgroups construidos dinámicamente en __init__.
    tecnico = forms.TypedChoiceField(
        coerce=int,
        empty_value=None,
        required=True,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        label='Técnico',
    )

    def __init__(self, *args, prioridad: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        # Inferir prioridad desde la instancia si no se pasa explícitamente
        if prioridad is None and self.instance and self.instance.pk:
            prioridad = self.instance.prioridad

        tecnicos = CustomUser.objects.filter(
            role=CustomUser.Roles.TECNICO,
            is_active=True,
        ).prefetch_related('especialidades_tecnico', 'horarios').order_by('first_name')

        # Separar técnicos con y sin capacidad para la prioridad del ticket
        con_capacidad = []
        sin_capacidad = []
        for t in tecnicos:
            carga = t.carga_trabajo_actual
            limite = t.max_carga_trabajo
            disponible = t.carga_disponible
            en_horario = t.esta_disponible_ahora()
            indicador_horario = '⏰' if en_horario else '💤'
            especialidades = t.especialidades_display or 'Sin especialidad'

            tiene_capacidad = prioridad is None or t.puede_aceptar_ticket(prioridad)
            indicador_carga = '🟢' if disponible > 3 else ('🟡' if disponible > 0 else '🔴')

            label = (
                f'{indicador_carga}{indicador_horario} {t.get_full_name()} '
                f'({especialidades}) — '
                f'Carga: {carga}/{limite}'
            )
            if tiene_capacidad:
                con_capacidad.append((t.pk, label))
            else:
                sin_capacidad.append((t.pk, label + ' · Sin capacidad'))

        # Construir choices con optgroups: disponibles primero, sobrecargados al final
        choices = [('', '— Seleccionar técnico —')]
        choices.extend(con_capacidad)
        if sin_capacidad:
            choices.append(('Sin capacidad', sin_capacidad))  # optgroup label legible

        # Asignar choices y widget personalizado
        self.fields['tecnico'].choices = choices
        self.fields['tecnico'].widget = _TecnicoSelectWidget(
            sobrecargados={pk for pk, _ in sin_capacidad},
            attrs={'class': SELECT_CLASS},
        )
        self.fields['tecnico'].widget.choices = choices

        # Pre-seleccionar técnico actual si existe
        if self.instance and self.instance.pk and self.instance.tecnico_id:
            self.fields['tecnico'].initial = self.instance.tecnico_id

    def clean_tecnico(self):
        """Convierte el PK del técnico seleccionado al objeto CustomUser."""
        pk = self.cleaned_data.get('tecnico')
        if not pk:
            raise forms.ValidationError('Debes seleccionar un técnico.')
        try:
            return CustomUser.objects.get(pk=pk, role=CustomUser.Roles.TECNICO, is_active=True)
        except CustomUser.DoesNotExist:
            raise forms.ValidationError('Técnico no válido o inactivo.')

    class Meta:
        model = Ticket
        fields = ['categoria', 'prioridad', 'tecnico']
        widgets = {
            'categoria': forms.Select(attrs={'class': SELECT_CLASS}),
            'prioridad': forms.Select(attrs={'class': SELECT_CLASS}),
            # 'tecnico' se gestiona íntegramente en __init__
        }


class _TecnicoSelectWidget(forms.Select):
    """Widget <select> que deshabilita las opciones de técnicos sobrecargados.

    Los técnicos sin capacidad quedan visibles (para transparencia) pero con
    el atributo ``disabled`` para impedir su selección accidental.
    """

    def __init__(self, *args, sobrecargados: set | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sobrecargados = sobrecargados or set()

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value and str(value) in {str(pk) for pk in self._sobrecargados}:
            option['attrs']['disabled'] = True
        return option


class InquilinoScheduleForm(forms.ModelForm):
    """Formulario que usa el inquilino para agendar la visita técnica.

    Los campos se rellenan automáticamente al hacer clic en un bloque
    libre del selector de disponibilidad (JS autocompleta los hidden inputs).
    """

    class Meta:
        model = Ticket
        fields = ['fecha_programada', 'hora_programada_inicio', 'hora_programada_fin']
        widgets = {
            'fecha_programada': forms.DateInput(attrs={
                'class': SELECT_CLASS,
                'type': 'date',
            }),
            'hora_programada_inicio': forms.TimeInput(attrs={
                'class': SELECT_CLASS,
                'type': 'time',
            }),
            'hora_programada_fin': forms.TimeInput(attrs={
                'class': SELECT_CLASS,
                'type': 'time',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha_programada')
        inicio = cleaned.get('hora_programada_inicio')
        fin = cleaned.get('hora_programada_fin')
        if not fecha:
            self.add_error('fecha_programada', 'Debes seleccionar una fecha.')
        if not inicio:
            self.add_error('hora_programada_inicio', 'Debes seleccionar una hora de inicio.')
        if inicio and fin and inicio >= fin:
            self.add_error('hora_programada_fin', 'La hora de fin debe ser posterior a la de inicio.')
        return cleaned


class TicketTransitionForm(forms.Form):
    """Formulario mínimo para cualquier transición que requiera nota."""

    nota = forms.CharField(
        label='Nota (opcional)',
        required=False,
        widget=forms.Textarea(attrs={
            'class': TEXTAREA_CLASS,
            'rows': 3,
            'placeholder': 'Detalles relevantes para el historial…',
        }),
    )


class TicketResolutionForm(forms.ModelForm):
    """Form que el técnico envía al cerrar el ticket."""

    class Meta:
        model = Ticket
        fields = ['notas_resolucion']
        widgets = {
            'notas_resolucion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 5,
                'placeholder': 'Resumen de la intervención, materiales, observaciones.',
            }),
        }


class MensajeForm(forms.ModelForm):
    """Mensaje en el hilo de comunicación técnico ↔ residente."""

    class Meta:
        model = MensajeTicket
        fields = ['mensaje']
        labels = {'mensaje': ''}
        widgets = {
            'mensaje': forms.Textarea(attrs={
                'class': (
                    'w-full border border-zinc-200 bg-white text-sm text-zinc-900 '
                    'px-4 py-3 outline-none focus:border-zinc-900 transition-colors '
                    'resize-none placeholder-zinc-400'
                ),
                'rows': 3,
                'placeholder': 'Escribe un mensaje…',
                'maxlength': 1000,
            }),
        }

