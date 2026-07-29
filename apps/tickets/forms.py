
from __future__ import annotations

import re

from django import forms
from django.db.models import Q

from apps.accounts.models import CustomUser
from apps.properties.models import Unidad

from .models import MensajeTicket, Ticket, TicketCategory, TicketPriority, TicketStatus

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


_PALABRAS_VACIAS = re.compile(
    r'^[\s\W]*(test|prueba|asd|asdf|xxx|zzz|111|123|hola|ok|si|no)[\s\W]*$',
    re.IGNORECASE,
)
_ESTADOS_ACTIVOS = {
    TicketStatus.CREADO_PENDIENTE_IA,
    TicketStatus.ANALIZADO_POR_IA,
    TicketStatus.PENDIENTE_VALIDACION,
    TicketStatus.APROBADO,
    TicketStatus.ASIGNADO,
    TicketStatus.EN_CAMINO,
    TicketStatus.EN_PROGRESO,
}


class TicketCreateForm(forms.ModelForm):

    def __init__(self, *args, inquilino=None, **kwargs):
        self._inquilino = inquilino
        super().__init__(*args, **kwargs)
        if inquilino is not None:
            unidad = getattr(inquilino, 'unidad_asignada', None)
            if unidad is not None:
                self.fields['unidad'].queryset = Unidad.objects.filter(pk=unidad.pk)
                self.fields['unidad'].initial = unidad.pk
            else:
                self.fields['unidad'].queryset = Unidad.objects.none()


    def clean_titulo(self):
        titulo = self.cleaned_data.get('titulo', '').strip()
        if len(titulo) < 10:
            raise forms.ValidationError(
                'El título debe tener al menos 10 caracteres. '
                'Sé específico: qué es, dónde está y qué ocurre.'
            )
        if _PALABRAS_VACIAS.match(titulo):
            raise forms.ValidationError(
                'El título no contiene información útil. '
                'Describe el problema real (ej: "Fuga de agua en cocina, piso 2").'
            )
        return titulo

    def clean_descripcion(self):
        descripcion = self.cleaned_data.get('descripcion', '').strip()
        if len(descripcion) < 30:
            raise forms.ValidationError(
                'La descripción debe tener al menos 30 caracteres. '
                'Incluye: qué ocurre, dónde exactamente y desde cuándo.'
            )
        return descripcion


    def clean(self):
        cleaned = super().clean()
        titulo = cleaned.get('titulo', '').strip().lower()
        unidad = cleaned.get('unidad')

        if not titulo or not unidad or not self._inquilino:
            return cleaned

        duplicado_exacto = Ticket.objects.filter(
            inquilino=self._inquilino,
            unidad=unidad,
            titulo__iexact=titulo,
            estado__in=_ESTADOS_ACTIVOS,
        ).first()
        if duplicado_exacto:
            raise forms.ValidationError(
                f'Ya tienes un ticket activo con este título en la misma unidad '
                f'({duplicado_exacto.codigo} — estado: {duplicado_exacto.get_estado_display()}). '
                'Espera a que sea resuelto antes de crear uno nuevo.'
            )

        activos_count = Ticket.objects.filter(
            inquilino=self._inquilino,
            estado__in=_ESTADOS_ACTIVOS,
        ).count()
        if activos_count >= 3:
            raise forms.ValidationError(
                f'Tienes {activos_count} tickets activos en este momento. '
                'El sistema permite un máximo de 3 tickets abiertos simultáneos. '
                'Espera a que alguno sea resuelto para abrir uno nuevo.'
            )

        return cleaned

    class Meta:
        model = Ticket
        fields = ['unidad', 'titulo', 'descripcion']
        widgets = {
            'unidad': forms.Select(attrs={'class': SELECT_CLASS}),
            'titulo': forms.TextInput(attrs={
                'class': INPUT_CLASS,
                'placeholder': 'Ej. Fuga de agua en cocina — mínimo 10 caracteres',
                'maxlength': 200,
                'minlength': '10',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'placeholder': 'Describe qué ocurre, dónde exactamente y desde cuándo. Mínimo 30 caracteres.',
                'rows': 5,
                'minlength': '30',
            }),
        }


class TicketAdminValidateForm(forms.ModelForm):

    tecnico = forms.TypedChoiceField(
        coerce=int,
        empty_value=None,
        required=True,
        widget=forms.Select(attrs={'class': SELECT_CLASS}),
        label='Técnico',
        error_messages={
            'required': 'Debes asignar un técnico antes de aprobar el ticket.',
        },
    )

    def __init__(self, *args, prioridad: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['categoria'].required = True
        self.fields['categoria'].choices = (
            [('', '— Seleccionar categoría —')] + list(TicketCategory.choices)
        )
        self.fields['categoria'].error_messages['required'] = (
            'Debes seleccionar una categoría.'
        )
        self.fields['prioridad'].required = True
        self.fields['prioridad'].error_messages['required'] = (
            'Debes seleccionar una prioridad.'
        )
        for nombre in ('categoria', 'prioridad'):
            self.fields[nombre].widget.attrs['required'] = 'required'

        if prioridad is None and self.instance and self.instance.pk:
            prioridad = self.instance.prioridad

        tecnicos = CustomUser.objects.filter(
            role=CustomUser.Roles.TECNICO,
            is_active=True,
        ).prefetch_related('especialidades_tecnico', 'horarios').order_by('first_name')

        con_capacidad = []
        sin_capacidad = []
        for t in tecnicos:
            carga = t.carga_trabajo_actual
            limite = t.max_carga_trabajo
            especialidades = t.especialidades_display or 'Sin especialidad'

            tiene_capacidad = prioridad is None or t.puede_aceptar_ticket(prioridad)

            label = (
                f'{t.get_full_name()} '
                f'({especialidades}) — '
                f'Carga: {carga}/{limite}'
            )
            if tiene_capacidad:
                con_capacidad.append((t.pk, label))
            else:
                sin_capacidad.append((t.pk, label + ' · Sin capacidad'))

        choices = [('', '— Seleccionar técnico —')]
        choices.extend(con_capacidad)
        if sin_capacidad:
            choices.append(('Sin capacidad', sin_capacidad))

        self.fields['tecnico'].choices = choices
        self.fields['tecnico'].widget = _TecnicoSelectWidget(
            sobrecargados={pk for pk, _ in sin_capacidad},
            attrs={'class': SELECT_CLASS, 'required': 'required'},
        )
        self.fields['tecnico'].widget.choices = choices

        if self.instance and self.instance.pk and self.instance.tecnico_id:
            self.fields['tecnico'].initial = self.instance.tecnico_id

    def clean_tecnico(self):
        pk = self.cleaned_data.get('tecnico')
        if not pk:
            raise forms.ValidationError(
                'Debes asignar un técnico antes de aprobar el ticket.'
            )
        try:
            return CustomUser.objects.get(pk=pk, role=CustomUser.Roles.TECNICO, is_active=True)
        except CustomUser.DoesNotExist:
            raise forms.ValidationError('Técnico no válido o inactivo.')

    def clean(self):
        cleaned = super().clean()
        tecnico = cleaned.get('tecnico')
        prioridad = cleaned.get('prioridad') or getattr(self.instance, 'prioridad', None)

        if tecnico and prioridad and not tecnico.puede_aceptar_ticket(prioridad):
            self.add_error(
                'tecnico',
                f'{tecnico.get_full_name()} ha alcanzado su límite de carga '
                f'({tecnico.carga_trabajo_actual}/{tecnico.max_carga_trabajo} puntos) '
                f'y no puede asumir un ticket de prioridad '
                f'{dict(TicketPriority.choices).get(prioridad, prioridad)}. '
                'Selecciona otro técnico o ajusta su límite.'
            )

        return cleaned

    class Meta:
        model = Ticket
        fields = ['categoria', 'prioridad', 'tecnico']
        widgets = {
            'categoria': forms.Select(attrs={'class': SELECT_CLASS}),
            'prioridad': forms.Select(attrs={'class': SELECT_CLASS}),
        }


class _TecnicoSelectWidget(forms.Select):

    def __init__(self, *args, sobrecargados: set | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sobrecargados = sobrecargados or set()

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value and str(value) in {str(pk) for pk in self._sobrecargados}:
            option['attrs']['disabled'] = True
        return option


class InquilinoScheduleForm(forms.ModelForm):

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

    def clean_notas_resolucion(self):
        notas = self.cleaned_data.get('notas_resolucion', '').strip()
        if not notas:
            raise forms.ValidationError(
                'Las notas de resolución son obligatorias. '
                'Documenta qué se hizo, qué materiales se usaron y el resultado.'
            )
        if len(notas) < 40:
            raise forms.ValidationError(
                f'Las notas deben tener al menos 40 caracteres ({len(notas)} actuales). '
                'Sé descriptivo: qué problema había, qué se hizo y cómo quedó.'
            )
        return notas

    class Meta:
        model = Ticket
        fields = ['notas_resolucion']
        widgets = {
            'notas_resolucion': forms.Textarea(attrs={
                'class': TEXTAREA_CLASS,
                'rows': 5,
                'minlength': '40',
                'placeholder': (
                    'Documenta la intervención: problema encontrado, '
                    'materiales usados, trabajos realizados y resultado final. '
                    'Mínimo 40 caracteres.'
                ),
            }),
        }


class MensajeForm(forms.ModelForm):

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

