/**
 * Chatbot RAG — InmoHelpdesk
 */
(function () {
    'use strict';

    const shell = document.getElementById('chatbot-panel');
    if (!shell) return;

    const aside = document.getElementById('chatbot-aside');
    const backdrop = document.getElementById('chatbot-backdrop');
    const fab = document.getElementById('chatbot-fab');
    const drawerClose = document.getElementById('chatbot-drawer-close');

    const messagesEl = shell.querySelector('.chatbot-messages');
    const form = shell.querySelector('.chatbot-form');
    const input = shell.querySelector('.chatbot-input');
    const sendBtn = shell.querySelector('.chatbot-send');
    const newSessionBtn = shell.querySelector('.chatbot-new-session');
    const escalateBox = shell.querySelector('.chatbot-escalate');
    const escalateText = shell.querySelector('.chatbot-escalate-text');
    const escalateLink = shell.querySelector('.chatbot-escalate-link');
    const scrollBottomBtn = shell.querySelector('.chatbot-scroll-bottom');
    const statusDot = document.getElementById('chatbot-status-dot');

    const SESSION_URL = shell.dataset.sessionUrl;
    const SEND_URL = shell.dataset.sendUrl;
    const TICKET_CREATE_URL = shell.dataset.ticketCreateUrl;

    const csrfToken = shell.querySelector('[name=csrfmiddlewaretoken]')?.value
        || getCookie('csrftoken');

    let pollingTimer = null;
    let isSending = false;
    const SCROLL_THRESHOLD = 80;
    const MQ_DESKTOP = window.matchMedia('(min-width: 1200px)');

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : '';
    }

    function apiFetch(url, options = {}) {
        return fetch(url, {
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'Accept': 'application/json',
                ...(options.headers || {}),
            },
            ...options,
        });
    }

    function isNearBottom() {
        const { scrollTop, scrollHeight, clientHeight } = messagesEl;
        return scrollHeight - scrollTop - clientHeight < SCROLL_THRESHOLD;
    }

    function scrollToBottom(force) {
        if (force || isNearBottom()) {
            messagesEl.scrollTop = messagesEl.scrollHeight;
            scrollBottomBtn?.classList.add('hidden');
        }
    }

    function updateScrollHint() {
        if (isNearBottom()) {
            scrollBottomBtn?.classList.add('hidden');
        } else {
            scrollBottomBtn?.classList.remove('hidden');
        }
    }

    function openDrawer() {
        aside?.classList.add('is-open');
        backdrop?.classList.add('is-visible');
        fab?.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
        setTimeout(() => input?.focus(), 350);
    }

    function closeDrawer() {
        aside?.classList.remove('is-open');
        backdrop?.classList.remove('is-visible');
        fab?.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatTime(iso) {
        if (!iso) return '';
        return new Date(iso).toLocaleTimeString('es-EC', { hour: '2-digit', minute: '2-digit' });
    }

    function renderMessage(msg) {
        const isUser = msg.rol === 'USUARIO';
        const isPending = msg.estado_proceso === 'PENDIENTE';
        const isError = msg.estado_proceso === 'ERROR';

        const wrapper = document.createElement('div');
        wrapper.className = `chatbot-msg-block chatbot-msg-animate ${isUser ? 'chatbot-msg-block--user' : ''}`;
        wrapper.dataset.uuid = msg.uuid;

        let bodyContent;
        if (isPending) {
            bodyContent = `<div class="flex items-center gap-2 py-1">
                <span class="chatbot-typing"><span></span><span></span><span></span></span>
                <span class="chatbot-typing-label">Consultando…</span>
            </div>`;
        } else if (isError) {
            bodyContent = `<p class="text-red-600">${escapeHtml(msg.contenido)}</p>`;
        } else {
            bodyContent = `<p class="whitespace-pre-wrap">${escapeHtml(msg.contenido)}</p>`;
        }

        const bubbleClass = isUser ? 'chatbot-bubble chatbot-bubble--user' : 'chatbot-bubble chatbot-bubble--assistant';

        wrapper.innerHTML = `
            <p class="chatbot-meta">${isUser ? 'Tú' : 'Asistente'} · ${formatTime(msg.creado_en)}</p>
            <div class="${bubbleClass}">${bodyContent}</div>`;

        return wrapper;
    }

    function updateMessage(msg) {
        const wasNearBottom = isNearBottom();
        const existing = messagesEl.querySelector(`[data-uuid="${msg.uuid}"]`);
        if (existing) {
            existing.replaceWith(renderMessage(msg));
        } else {
            messagesEl.appendChild(renderMessage(msg));
        }
        if (wasNearBottom || msg.rol === 'USUARIO') {
            scrollToBottom(true);
        } else {
            updateScrollHint();
        }
        handleEscalation(msg);
    }

    function handleEscalation(msg) {
        if (!escalateBox) return;
        if (msg.rol !== 'ASISTENTE' || msg.estado_proceso !== 'COMPLETADO') return;
        const meta = msg.metadata || {};
        if (meta.requiere_tecnico) {
            escalateText.textContent = meta.titulo_ticket_sugerido
                || 'Si no pudiste resolverlo, registra un ticket.';
            const params = new URLSearchParams();
            if (meta.titulo_ticket_sugerido) params.set('titulo', meta.titulo_ticket_sugerido);
            if (meta.descripcion_ticket_sugerida) params.set('descripcion', meta.descripcion_ticket_sugerida);
            escalateLink.href = params.toString() ? `${TICKET_CREATE_URL}?${params}` : TICKET_CREATE_URL;
            escalateBox.classList.remove('hidden');
        } else {
            escalateBox.classList.add('hidden');
        }
    }

    function clearWelcome() {
        const welcome = messagesEl.querySelector('.chatbot-welcome');
        if (welcome) welcome.remove();
    }

    function getWelcomeHtml() {
        return `<div class="chatbot-welcome chatbot-msg-block">
            <p class="chatbot-meta">Asistente</p>
            <div class="chatbot-bubble chatbot-bubble--assistant"><p>Nueva conversación. ¿En qué puedo ayudarte?</p></div>
            <div class="flex flex-wrap gap-1.5 mt-2">
                <button type="button" class="chatbot-suggestion" data-prompt="¿Cómo cierro la llave de paso de agua?">Llave de paso</button>
            </div>
        </div>`;
    }

    function loadSession() {
        apiFetch(SESSION_URL)
            .then(r => r.json())
            .then(data => {
                const msgs = data.mensajes || [];
                if (msgs.length === 0) return;
                clearWelcome();
                msgs.forEach(msg => {
                    if (msg.rol !== 'SISTEMA') {
                        messagesEl.appendChild(renderMessage(msg));
                    }
                });
                scrollToBottom(true);
                const lastAssistant = [...msgs].reverse().find(m => m.rol === 'ASISTENTE');
                if (lastAssistant) handleEscalation(lastAssistant);
            })
            .catch(() => {
                if (statusDot) {
                    statusDot.innerHTML = '<span class="chatbot-status__dot" style="background:#ef4444"></span> <span style="color:#b91c1c">Offline</span>';
                }
            });
    }

    function pollMessage(uuid, attempts = 0) {
        if (attempts >= 60) {
            updateMessage({
                uuid,
                rol: 'ASISTENTE',
                contenido: 'Tiempo de espera agotado. Intenta de nuevo.',
                estado_proceso: 'ERROR',
                creado_en: new Date().toISOString(),
            });
            setSending(false);
            return;
        }

        apiFetch(`/api/chat/messages/${uuid}/`)
            .then(r => r.json())
            .then(msg => {
                updateMessage(msg);
                if (msg.estado_proceso === 'PENDIENTE') {
                    pollingTimer = setTimeout(() => pollMessage(uuid, attempts + 1), 1500);
                } else {
                    setSending(false);
                    input?.focus();
                }
            })
            .catch(() => {
                pollingTimer = setTimeout(() => pollMessage(uuid, attempts + 1), 2000);
            });
    }

    function setSending(state) {
        isSending = state;
        if (sendBtn) sendBtn.disabled = state;
        if (input) input.disabled = state;
    }

    function sendMessage(text) {
        const content = (text || input?.value || '').trim();
        if (!content || isSending) return;

        if (!MQ_DESKTOP.matches) openDrawer();

        clearWelcome();
        escalateBox?.classList.add('hidden');
        setSending(true);
        if (input) {
            input.value = '';
            input.style.height = 'auto';
        }

        apiFetch(SEND_URL, {
            method: 'POST',
            body: JSON.stringify({ contenido: content }),
        })
            .then(r => {
                if (!r.ok) throw new Error('Error');
                return r.json();
            })
            .then(data => {
                messagesEl.appendChild(renderMessage(data.user_message));
                messagesEl.appendChild(renderMessage(data.assistant_message));
                scrollToBottom(true);
                pollMessage(data.assistant_message.uuid);
            })
            .catch(() => {
                setSending(false);
                messagesEl.appendChild(renderMessage({
                    uuid: 'err-' + Date.now(),
                    rol: 'ASISTENTE',
                    contenido: 'No se pudo enviar. Verifica tu conexión.',
                    estado_proceso: 'ERROR',
                    creado_en: new Date().toISOString(),
                }));
                scrollToBottom(true);
            });
    }

    function resetConversation() {
        if (isSending) return;
        apiFetch(SESSION_URL, { method: 'POST', body: '{}' })
            .then(() => {
                messagesEl.innerHTML = getWelcomeHtml();
                escalateBox?.classList.add('hidden');
                bindSuggestions();
                scrollToBottom(true);
            });
    }

    function bindSuggestions() {
        shell.querySelectorAll('.chatbot-suggestion').forEach(btn => {
            btn.addEventListener('click', () => sendMessage(btn.dataset.prompt));
        });
    }

    messagesEl?.addEventListener('scroll', updateScrollHint, { passive: true });
    scrollBottomBtn?.addEventListener('click', () => scrollToBottom(true));
    form?.addEventListener('submit', e => { e.preventDefault(); sendMessage(); });
    input?.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    input?.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 104) + 'px';
    });
    newSessionBtn?.addEventListener('click', () => {
        if (confirm('¿Iniciar una nueva conversación?')) resetConversation();
    });

    fab?.addEventListener('click', () => {
        if (aside?.classList.contains('is-open')) closeDrawer();
        else openDrawer();
    });
    backdrop?.addEventListener('click', closeDrawer);
    drawerClose?.addEventListener('click', closeDrawer);

    bindSuggestions();
    loadSession();
})();
