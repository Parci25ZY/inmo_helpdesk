/**
 * INMOHELPDESK — FLOATING TAB BAR CONTROLLER
 * Maneja auto-ocultar al escribir (foco en inputs/teclado virtual),
 * auto-ocultar al hacer scroll hacia abajo, y el menú de Gestión en tablet/móvil.
 * Blindado contra rebotes táctiles y scroll accidental al tocar botones.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {
        const tabBar = document.getElementById('floating-tab-bar');
        if (!tabBar) return;

        const adminBtn = document.getElementById('floating-tab-admin-btn');
        const adminPopup = document.getElementById('floating-admin-popup');
        const notifBtn = document.getElementById('floating-tab-notif-btn');
        const notifDropdown = document.getElementById('notif-dropdown');
        const fab = document.getElementById('chatbot-fab');
        const aside = document.getElementById('chatbot-aside');

        let isHidden = false;
        let isInputFocused = false;
        let lastScrollY = window.scrollY || window.pageYOffset;
        let scrollTimer = null;
        let ignoreHideUntil = 0; // Temporizador para evitar ocultamiento accidental al pulsar
        const SCROLL_THRESHOLD = 25;

        // ── 0. BLINDAJE TÁCTIL (Evitar ocultar la barra al tocar o hacer clic) ──
        const protectedZones = [tabBar, adminPopup, notifBtn, notifDropdown].filter(Boolean);
        protectedZones.forEach(zone => {
            ['pointerdown', 'touchstart', 'click'].forEach(evtType => {
                zone.addEventListener(evtType, () => {
                    ignoreHideUntil = Date.now() + 1500;
                }, { passive: true });
            });
        });

        // ── 1. AUTO-OCULTAR AL ESCRIBIR O ENFOCAR CAMPOS DE TEXTO ─────────
        function handleFocusIn(e) {
            if (window.innerWidth >= 1200) return;
            if (e.target.closest('#floating-tab-bar, #floating-admin-popup, #notif-dropdown, .floating-tab-btn')) {
                return;
            }
            const type = e.target.type;
            if (type === 'checkbox' || type === 'radio' || type === 'submit' || type === 'button') return;

            // Verificar que sea un campo de entrada real
            const tagName = e.target.tagName;
            const isTextInput = tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT' || e.target.getAttribute('contenteditable') === 'true';
            if (!isTextInput) return;

            isInputFocused = true;
            hideTabBar();
            closeAdminPopup();
        }

        function handleFocusOut(e) {
            if (window.innerWidth >= 1200) return;
            isInputFocused = false;
            setTimeout(() => {
                const activeEl = document.activeElement;
                const isStillInput = activeEl && (
                    activeEl.tagName === 'INPUT' ||
                    activeEl.tagName === 'TEXTAREA' ||
                    activeEl.tagName === 'SELECT' ||
                    activeEl.getAttribute('contenteditable') === 'true'
                ) && activeEl.type !== 'checkbox' && activeEl.type !== 'radio' && !activeEl.closest('#floating-tab-bar, #floating-admin-popup');

                if (!isStillInput && !aside?.classList.contains('is-open')) {
                    showTabBar();
                }
            }, 200);
        }

        document.addEventListener('focusin', handleFocusIn);
        document.addEventListener('focusout', handleFocusOut);

        // ── 2. AUTO-OCULTAR AL HACER SCROLL (SCROLL-DOWN HIDE) ───────────
        window.addEventListener('scroll', () => {
            if (window.innerWidth >= 1200 || isInputFocused) return;

            // Si el usuario acaba de tocar la Tab Bar o tiene el menú de gestión/notificaciones abierto, NO ocultar
            if (Date.now() < ignoreHideUntil || adminPopup?.classList.contains('is-open') || (notifDropdown && !notifDropdown.classList.contains('hidden'))) {
                return;
            }

            if (scrollTimer) cancelAnimationFrame(scrollTimer);

            scrollTimer = requestAnimationFrame(() => {
                const currentScrollY = window.scrollY || window.pageYOffset;
                const delta = currentScrollY - lastScrollY;

                if (currentScrollY < 40) {
                    showTabBar();
                } else if (delta > SCROLL_THRESHOLD && !isHidden) {
                    if (Date.now() >= ignoreHideUntil && !adminPopup?.classList.contains('is-open') && (notifDropdown && notifDropdown.classList.contains('hidden'))) {
                        hideTabBar();
                        closeAdminPopup();
                    }
                } else if (delta < -15 && isHidden && !isInputFocused) {
                    showTabBar();
                }

                lastScrollY = currentScrollY;
            });
        }, { passive: true });

        // ── 3. FUNCIONES DE OCULTAR / MOSTRAR Y FAB LOWERS ───────────────
        function hideTabBar() {
            if (isHidden || Date.now() < ignoreHideUntil || adminPopup?.classList.contains('is-open') || (notifDropdown && !notifDropdown.classList.contains('hidden'))) return;
            isHidden = true;
            tabBar.classList.add('tab-bar--hidden');
            if (fab) fab.classList.add('fab--lowered');
        }

        function showTabBar() {
            if (!isHidden) return;
            isHidden = false;
            tabBar.classList.remove('tab-bar--hidden');
            if (fab) fab.classList.remove('fab--lowered');
        }

        // ── 4. CONTROL DEL MENÚ EMERGENTE ADMINISTRATIVO (GESTIÓN) ───────
        if (adminBtn && adminPopup) {
            adminBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                ignoreHideUntil = Date.now() + 2500; // Dar 2.5s de protección extra al abrir el menú
                const isOpen = adminPopup.classList.contains('is-open');
                if (isOpen) {
                    closeAdminPopup();
                } else {
                    openAdminPopup();
                }
            });

            document.addEventListener('click', (e) => {
                if (adminPopup.classList.contains('is-open') &&
                    !adminPopup.contains(e.target) &&
                    !adminBtn.contains(e.target)) {
                    closeAdminPopup();
                }
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') closeAdminPopup();
            });
        }

        function openAdminPopup() {
            if (!adminPopup) return;
            adminPopup.classList.remove('hidden');
            requestAnimationFrame(() => {
                adminPopup.classList.add('is-open');
                if (adminBtn) adminBtn.classList.add('is-active');
            });
        }

        function closeAdminPopup() {
            if (!adminPopup || !adminPopup.classList.contains('is-open')) return;
            adminPopup.classList.remove('is-open');
            if (adminBtn) adminBtn.classList.remove('is-active');
            setTimeout(() => {
                if (!adminPopup.classList.contains('is-open')) {
                    adminPopup.classList.add('hidden');
                }
            }, 250);
        }

        // ── 5. ACCIÓN RÁPIDA DE NOTIFICACIONES EN LA TAB BAR ─────────────
        if (notifBtn) {
            notifBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                ignoreHideUntil = Date.now() + 3000;
                closeAdminPopup();
                if (window.__toggleNotifDropdown) {
                    window.__toggleNotifDropdown();
                }
            });
        }

        // Sincronizar el cajón del chatbot: al cerrar el chatbot, restaurar la tab bar
        const drawerCloseBtn = document.getElementById('chatbot-drawer-close');
        const backdropEl = document.getElementById('chatbot-backdrop');
        [drawerCloseBtn, backdropEl].forEach(btn => {
            if (btn) {
                btn.addEventListener('click', () => {
                    setTimeout(() => {
                        if (!isInputFocused) showTabBar();
                    }, 200);
                });
            }
        });
    });
})();
