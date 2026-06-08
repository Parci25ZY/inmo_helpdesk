/**
 * Recuperación de contraseña — modal en login + página confirmación
 */
(function () {
    'use strict';

    const API = {
        request: '/api/auth/password-reset/request/',
        verify: '/api/auth/password-reset/verify/',
        confirm: '/api/auth/password-reset/confirm/',
    };

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : '';
    }

    function apiPost(url, body) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify(body),
        }).then(async (r) => {
            const data = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(data.detail || 'Error en la solicitud.');
            return data;
        });
    }

    function storeTokens(access, refresh) {
        if (access) localStorage.setItem('inmo_access_token', access);
        if (refresh) localStorage.setItem('inmo_refresh_token', refresh);
    }

    /* ── Modal en login ── */
    const modal = document.getElementById('pr-modal');
    if (modal) {
        const openBtn = document.getElementById('pr-open-modal');
        const closeBtn = document.getElementById('pr-close-modal');
        const backdrop = modal.querySelector('.pr-modal__backdrop');
        const steps = modal.querySelectorAll('.pr-step');
        const alertEl = document.getElementById('pr-alert');

        const emailInput = document.getElementById('pr-email');
        const codeInput = document.getElementById('pr-code');
        const btnRequest = document.getElementById('pr-btn-request');
        const btnVerify = document.getElementById('pr-btn-verify');
        const btnContinue = document.getElementById('pr-btn-continue');
        const backLink = document.getElementById('pr-back-email');

        let currentEmail = '';

        function showAlert(msg, type) {
            alertEl.textContent = msg;
            alertEl.className = `pr-alert pr-alert--${type}`;
            alertEl.hidden = false;
        }

        function hideAlert() {
            alertEl.hidden = true;
        }

        function goStep(name) {
            steps.forEach(s => s.classList.toggle('is-active', s.dataset.step === name));
            hideAlert();
        }

        function openModal() {
            modal.classList.add('is-open');
            modal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            goStep('email');
            emailInput?.focus();
        }

        function closeModal() {
            modal.classList.remove('is-open');
            modal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        openBtn?.addEventListener('click', openModal);
        closeBtn?.addEventListener('click', closeModal);
        backdrop?.addEventListener('click', closeModal);

        backLink?.addEventListener('click', () => goStep('email'));

        btnRequest?.addEventListener('click', () => {
            const email = (emailInput?.value || '').trim();
            if (!email) {
                showAlert('Ingresa tu correo electrónico.', 'error');
                return;
            }
            btnRequest.disabled = true;
            apiPost(API.request, { email })
                .then(() => {
                    currentEmail = email;
                    goStep('code');
                    codeInput?.focus();
                })
                .catch(err => showAlert(err.message, 'error'))
                .finally(() => { btnRequest.disabled = false; });
        });

        btnVerify?.addEventListener('click', () => {
            const code = (codeInput?.value || '').trim();
            if (code.length !== 6) {
                showAlert('El código debe tener 6 dígitos.', 'error');
                return;
            }
            btnVerify.disabled = true;
            apiPost(API.verify, { email: currentEmail, code })
                .then(data => {
                    sessionStorage.setItem('inmo_reset_token', data.reset_token);
                    sessionStorage.setItem('inmo_reset_email', currentEmail);
                    goStep('success');
                })
                .catch(err => showAlert(err.message, 'error'))
                .finally(() => { btnVerify.disabled = false; });
        });

        btnContinue?.addEventListener('click', () => {
            window.location.href = '/recuperar-contrasena/';
        });

        codeInput?.addEventListener('input', () => {
            codeInput.value = codeInput.value.replace(/\D/g, '').slice(0, 6);
        });
    }

    /* ── Página confirmar contraseña ── */
    const confirmForm = document.getElementById('pr-confirm-form');
    if (confirmForm) {
        const token = sessionStorage.getItem('inmo_reset_token')
            || new URLSearchParams(window.location.search).get('token');
        const alertBox = document.getElementById('pr-confirm-alert');
        const submitBtn = document.getElementById('pr-confirm-submit');

        if (!token) {
            if (alertBox) {
                alertBox.textContent = 'No hay un token válido. Solicita un nuevo código desde el login.';
                alertBox.className = 'pr-alert pr-alert--error';
                alertBox.hidden = false;
            }
            confirmForm.querySelectorAll('input, button').forEach(el => { el.disabled = true; });
        }

        confirmForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const pwd1 = document.getElementById('pr-new-password')?.value || '';
            const pwd2 = document.getElementById('pr-new-password-confirm')?.value || '';

            if (pwd1 !== pwd2) {
                alertBox.textContent = 'Las contraseñas no coinciden.';
                alertBox.className = 'pr-alert pr-alert--error';
                alertBox.hidden = false;
                return;
            }

            submitBtn.disabled = true;
            apiPost(API.confirm, {
                reset_token: token,
                new_password: pwd1,
                new_password_confirm: pwd2,
            })
                .then(data => {
                    storeTokens(data.access, data.refresh);
                    sessionStorage.removeItem('inmo_reset_token');
                    sessionStorage.removeItem('inmo_reset_email');
                    window.location.href = '/dashboard/';
                })
                .catch(err => {
                    alertBox.textContent = err.message;
                    alertBox.className = 'pr-alert pr-alert--error';
                    alertBox.hidden = false;
                    submitBtn.disabled = false;
                });
        });
    }
})();
