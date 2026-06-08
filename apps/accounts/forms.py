from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ('first_name', 'last_name', 'email', 'phone', 'role')

class CustomAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(widget=forms.EmailInput(attrs={
        'placeholder': 'Correo Electrónico',
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Contraseña',
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
    }))

class UserEditForm(UserChangeForm):
    """Formulario para editar usuarios existentes en el panel administrativo"""
    password = None  # Ocultar el campo de contraseña en la edición directa
    
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'phone', 'role', 'is_active', 'is_staff']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Nombres'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Apellidos'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Correo Electrónico'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal',
                'placeholder': 'Teléfono'
            }),
            'role': forms.Select(attrs={
                'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-text-dark dark:text-text-light focus:outline-0 focus:ring-2 focus:ring-primary/50 border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 h-14 placeholder:text-zinc-400 dark:placeholder-zinc-500 p-3.5 text-base font-normal'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-primary'
            }),
            'is_staff': forms.CheckboxInput(attrs={
                'class': 'form-checkbox h-5 w-5 text-primary'
            }),
        }

_INPUT_CLASS = (
    'w-full bg-transparent border-0 border-b-2 border-zinc-200 py-3 px-0 '
    'text-base font-medium text-zinc-900 placeholder-zinc-300 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)
_SELECT_CLASS = (
    'w-full bg-white border border-zinc-200 rounded py-3 px-3 '
    'text-base font-medium text-zinc-900 outline-none '
    'focus:border-zinc-900 transition-colors duration-200'
)

class UserCreateForm(UserCreationForm):
    """Formulario para crear nuevos usuarios en el panel administrativo"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget = forms.PasswordInput(attrs={
            'class': _INPUT_CLASS,
            'placeholder': '••••••••••',
        })
        self.fields['password2'].widget = forms.PasswordInput(attrs={
            'class': _INPUT_CLASS,
            'placeholder': '••••••••••',
        })

    class Meta:
        model = CustomUser
        fields = ['email', 'first_name', 'last_name', 'phone', 'role']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'correo@ejemplo.com',
            }),
            'first_name': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. Carlos',
            }),
            'last_name': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. Ramírez',
            }),
            'phone': forms.TextInput(attrs={
                'class': _INPUT_CLASS,
                'placeholder': 'Ej. +593 99 000 0000',
            }),
            'role': forms.Select(attrs={
                'class': _SELECT_CLASS,
            }),
        }
