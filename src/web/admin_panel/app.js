const TOKEN_KEY = "mtproxy_admin_token";

const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    authConfig: null,
    nodesPollTimer: null,
};

function getAuthHeaders() {
    return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function apiRequest(path, options = {}) {
    const response = await fetch(`/api/admin${path}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...getAuthHeaders(),
            ...(options.headers || {}),
        },
    });
    const isJson = response.headers.get("content-type")?.includes("application/json");
    const data = isJson ? await response.json() : null;
    if (!response.ok) {
        const detail = data?.detail || response.statusText;
        throw new Error(`${response.status}: ${detail}`);
    }
    return data;
}

function formatDate(value) {
    if (!value) {
        return "—";
    }
    return new Date(value).toLocaleString("ru-RU");
}

function money(value) {
    const num = Number(value || 0);
    return `$${num.toFixed(2)}`;
}

function setAuthState() {
    const authState = document.getElementById("auth-state");
    const loginSection = document.getElementById("login-section");
    const adminSection = document.getElementById("admin-section");
    const logoutBtn = document.getElementById("logout-btn");

    const authorized = Boolean(state.token);
    authState.textContent = authorized ? "Авторизован" : "Не авторизован";
    loginSection.hidden = authorized;
    adminSection.hidden = !authorized;
    logoutBtn.hidden = !authorized;
}

function setupTabs() {
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll(".tab-btn").forEach((item) => item.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach((item) => item.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(`tab-${tab}`).classList.add("active");
        });
    });
}

async function loadAuthConfig() {
    state.authConfig = await apiRequest("/auth/config", { method: "GET" });
    const container = document.getElementById("telegram-login-container");
    container.innerHTML = "";

    if (!state.authConfig.telegram_login_enabled || !state.authConfig.telegram_bot_name) {
        const warning = document.createElement("p");
        warning.textContent = "Telegram Login не настроен. Используйте резервный вход.";
        container.appendChild(warning);
        return;
    }

    window.onTelegramAuth = async (user) => {
        try {
            const data = await apiRequest("/login/telegram", {
                method: "POST",
                body: JSON.stringify(user),
            });
            state.token = data.access_token;
            localStorage.setItem(TOKEN_KEY, state.token);
            await onAuthorized();
        } catch (error) {
            alert(`Ошибка Telegram входа: ${error.message}`);
        }
    };

    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", state.authConfig.telegram_bot_name);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    container.appendChild(script);
}

function renderTable(containerId, headers, rows) {
    const container = document.getElementById(containerId);
    if (!rows.length) {
        container.innerHTML = "<p>Нет данных.</p>";
        return;
    }
    const thead = `<tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
    const tbody = rows.map((r) => `<tr>${r}</tr>`).join("");
    container.innerHTML = `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

async function loadDashboard() {
    const data = await apiRequest("/stats");
    const kpi = document.getElementById("kpi-grid");
    const cards = [
        ["Пользователей", data.users_total],
        ["Активных подписок", data.subscriptions_active],
        ["Нод всего", data.nodes_total],
        ["Нод online", data.nodes_online],
        ["Нод offline", data.nodes_offline],
        ["Средняя загрузка", `${data.nodes_avg_load_percent}%`],
        ["Выручка total", money(data.revenue.total_revenue)],
        ["Выручка month", money(data.revenue.month_revenue)],
        ["Выручка week", money(data.revenue.week_revenue)],
        ["Выручка today", money(data.revenue.today_revenue)],
    ];
    kpi.innerHTML = cards
        .map(
            ([label, value]) => `<div class="kpi-card">
                <div class="kpi-label">${label}</div>
                <div class="kpi-value">${value}</div>
            </div>`
        )
        .join("");

    const nodeRows = data.nodes.map((n) => {
        const cls = n.availability_status;
        return `
            <td>${n.country_flag} ${n.name}</td>
            <td><span class="badge ${cls}">${n.availability_status}</span></td>
            <td>${n.current_users}/${n.max_users}</td>
            <td>${n.free_slots}</td>
            <td>${n.load_percent}%</td>
            <td>${n.availability_reason}</td>
            <td>${formatDate(n.last_check_at)}</td>
        `;
    });
    renderTable(
        "nodes-dashboard",
        ["Нода", "Статус", "Пользователи", "Свободно", "Загрузка", "Причина", "Проверено"],
        nodeRows
    );
}

async function loadUsers() {
    const search = document.getElementById("users-search").value.trim();
    const data = await apiRequest(`/users?limit=100&offset=0&search=${encodeURIComponent(search)}`);
    const rows = data.users.map((u) => `
        <td>${u.id}</td>
        <td>${u.telegram_id}</td>
        <td>${u.username || ""}</td>
        <td>${u.first_name || ""}</td>
        <td>${u.used_trial ? "Да" : "Нет"}</td>
        <td>${u.is_banned ? "Да" : "Нет"}</td>
        <td>${formatDate(u.created_at)}</td>
        <td>
            <button class="btn ${u.is_banned ? "" : "warning"}" onclick="toggleBan(${u.id}, ${u.is_banned})">
                ${u.is_banned ? "Разбан" : "Бан"}
            </button>
            <button class="btn danger" onclick="deleteUser(${u.id})">Удалить</button>
        </td>
    `);
    renderTable(
        "users-table",
        ["ID", "Telegram ID", "Username", "Имя", "Trial", "Бан", "Создан", "Действия"],
        rows
    );
}

async function loadNodes() {
    const data = await apiRequest("/nodes?include_health=true");
    const rows = data.nodes.map((n) => `
        <td>${n.id}</td>
        <td>${n.country_flag} ${n.name}</td>
        <td>${n.host}</td>
        <td>${n.port}</td>
        <td>${n.socks5_port || 1080}</td>
        <td><span class="badge ${n.availability_status}">${n.availability_status}</span></td>
        <td>${n.current_users}/${n.max_users}</td>
        <td>${n.free_slots}</td>
        <td>${n.load_percent}%</td>
        <td>${n.is_active ? "Да" : "Нет"}</td>
        <td>
            <button class="btn" onclick="testNode(${n.id})">Проверить</button>
            <button class="btn" onclick="editNode(${n.id})">Редактировать</button>
            <button class="btn ${n.is_active ? "warning" : ""}" onclick="toggleNode(${n.id}, ${n.is_active})">
                ${n.is_active ? "Отключить" : "Включить"}
            </button>
            <button class="btn danger" onclick="deleteNode(${n.id})">Удалить</button>
        </td>
    `);
    renderTable(
        "nodes-table",
        ["ID", "Нода", "Host", "MTPort", "S5Port", "Статус", "Польз.", "Свободно", "Load", "Active", "Actions"],
        rows
    );
}

async function loadSubscriptions() {
    const status = document.getElementById("subs-status-filter").value;
    const data = await apiRequest(
        `/subscriptions?limit=100&offset=0&status_filter=${encodeURIComponent(status)}`
    );
    const rows = data.subscriptions.map((s) => `
        <td>${s.id}</td>
        <td>${s.telegram_id || ""} @${s.username || ""}</td>
        <td>${s.plan_name}</td>
        <td>${s.node_name}</td>
        <td>${s.access_type || "mtproto"}</td>
        <td>${s.status}</td>
        <td>${formatDate(s.expires_at)}</td>
        <td>
            <button class="btn" onclick="extendSub(${s.id})">Продлить</button>
            <button class="btn warning" onclick="rotateSub(${s.id})">Ротация</button>
            <button class="btn warning" onclick="changeSubNode(${s.id})">Сменить ноду</button>
            <button class="btn ${s.status === "active" ? "warning" : ""}" onclick="toggleSubStatus(${s.id}, '${s.status}')">
                ${s.status === "active" ? "Cancel" : "Activate"}
            </button>
            <button class="btn danger" onclick="deleteSub(${s.id})">Удалить</button>
        </td>
    `);
    renderTable(
        "subs-table",
        ["ID", "Пользователь", "Тариф", "Нода", "Тип", "Статус", "До", "Actions"],
        rows
    );
}

async function loadPayments() {
    const data = await apiRequest("/payments?limit=100&offset=0");
    const rows = data.payments.map((p) => `
        <td>${p.id}</td>
        <td>${p.user_id}</td>
        <td>${p.plan_name}</td>
        <td>${p.node_name || "—"}</td>
        <td>${p.access_type || "mtproto"}</td>
        <td>${money(p.amount_usd)}</td>
        <td>${p.status}</td>
        <td>${formatDate(p.created_at)}</td>
        <td>${formatDate(p.paid_at)}</td>
        <td>
            <button class="btn" onclick="editPayment(${p.id})">Редактировать</button>
            <button class="btn danger" onclick="deletePayment(${p.id})">Удалить</button>
        </td>
    `);
    renderTable(
        "payments-table",
        ["ID", "User", "Plan", "Node", "Type", "Amount", "Status", "Created", "Paid", "Actions"],
        rows
    );
}

async function loadPlans() {
    const data = await apiRequest("/plans");
    const rows = data.plans.map((p) => `
        <td>${p.id}</td>
        <td>${p.name}</td>
        <td>${p.duration_days}</td>
        <td>${money(p.price_usd)}</td>
        <td>${p.is_trial ? "Да" : "Нет"}</td>
        <td>${p.is_active ? "Да" : "Нет"}</td>
        <td>
            <button class="btn" onclick="editPlan(${p.id})">Редактировать</button>
            <button class="btn ${p.is_active ? "warning" : ""}" onclick="togglePlan(${p.id}, ${p.is_active})">
                ${p.is_active ? "Деактивировать" : "Активировать"}
            </button>
            <button class="btn danger" onclick="deletePlan(${p.id})">Удалить</button>
        </td>
    `);
    renderTable("plans-table", ["ID", "Название", "Дни", "Цена", "Trial", "Active", "Actions"], rows);
}

async function onAuthorized() {
    setAuthState();
    await Promise.all([loadDashboard(), loadUsers(), loadNodes(), loadSubscriptions(), loadPayments(), loadPlans()]);
    if (state.nodesPollTimer) {
        clearInterval(state.nodesPollTimer);
    }
    state.nodesPollTimer = setInterval(() => {
        loadNodes().catch(console.error);
        loadDashboard().catch(console.error);
    }, 20000);
}

async function safeAction(fn) {
    try {
        await fn();
    } catch (error) {
        alert(`Ошибка: ${error.message}`);
    }
}

window.toggleBan = (userId, isBanned) => safeAction(async () => {
    const action = isBanned ? "unban" : "ban";
    await apiRequest(`/users/${userId}/${action}`, { method: "POST" });
    await loadUsers();
});

window.deleteUser = (userId) => safeAction(async () => {
    if (!confirm("Удалить пользователя? Это удалит связанные данные.")) {
        return;
    }
    await apiRequest(`/users/${userId}`, { method: "DELETE" });
    await loadUsers();
});

window.toggleNode = (nodeId, isActive) => safeAction(async () => {
    const endpoint = isActive ? "deactivate" : "activate";
    await apiRequest(`/nodes/${nodeId}/${endpoint}`, { method: "PATCH" });
    await loadNodes();
    await loadDashboard();
});

window.testNode = (nodeId) => safeAction(async () => {
    const result = await apiRequest(`/nodes/${nodeId}/test-connection`, { method: "POST" });
    alert(`Статус: ${result.status}\nПричина: ${result.reason}`);
    await loadNodes();
});

window.deleteNode = (nodeId) => safeAction(async () => {
    if (!confirm("Удалить ноду? Должно не быть активных подписок.")) {
        return;
    }
    await apiRequest(`/nodes/${nodeId}`, { method: "DELETE" });
    await loadNodes();
});

window.editNode = (nodeId) => safeAction(async () => {
    const current = await apiRequest(`/nodes/${nodeId}`);
    const node = current.node;
    const name = prompt("Имя ноды:", node.name);
    if (!name) {
        return;
    }
    const host = prompt("Host:", node.host);
    const port = Number(prompt("MTProto port:", node.port));
    const socks5Port = Number(prompt("SOCKS5 port:", node.socks5_port || 1080));
    const country = prompt("Country:", node.country);
    const countryFlag = prompt("Country flag:", node.country_flag || "");
    const agentUrl = prompt("Agent URL:", node.agent_url);
    const agentApiKey = prompt("Agent API key:", node.agent_api_key);
    const maxUsers = Number(prompt("Max users:", node.max_users));
    await apiRequest(`/nodes/${nodeId}`, {
        method: "PUT",
        body: JSON.stringify({
            name,
            host,
            port,
            country,
            country_flag: countryFlag,
            agent_url: agentUrl,
            agent_api_key: agentApiKey,
            max_users: maxUsers,
            socks5_port: socks5Port,
        }),
    });
    await loadNodes();
});

window.extendSub = (subscriptionId) => safeAction(async () => {
    const days = Number(prompt("Продлить на сколько дней?", "30"));
    if (!days || days < 1) {
        return;
    }
    await apiRequest(`/subscriptions/${subscriptionId}/extend`, {
        method: "POST",
        body: JSON.stringify({ days }),
    });
    await loadSubscriptions();
});

window.rotateSub = (subscriptionId) => safeAction(async () => {
    const country = prompt("Страна для ротации (как в БД, напр. Finland):", "");
    if (!country) {
        return;
    }
    const result = await apiRequest(`/subscriptions/${subscriptionId}/rotate`, {
        method: "POST",
        body: JSON.stringify({ country }),
    });
    alert(`Результат ротации: ${JSON.stringify(result.result)}`);
    await loadSubscriptions();
});

window.changeSubNode = (subscriptionId) => safeAction(async () => {
    const country = prompt("Страна целевой ноды:", "");
    if (!country) {
        return;
    }
    const result = await apiRequest(`/subscriptions/${subscriptionId}/change-node`, {
        method: "POST",
        body: JSON.stringify({ country }),
    });
    alert(`Результат переноса: ${JSON.stringify(result.result)}`);
    await loadSubscriptions();
});

window.toggleSubStatus = (subscriptionId, statusValue) => safeAction(async () => {
    const endpoint = statusValue === "active" ? "cancel" : "activate";
    await apiRequest(`/subscriptions/${subscriptionId}/${endpoint}`, { method: "POST" });
    await loadSubscriptions();
});

window.deleteSub = (subscriptionId) => safeAction(async () => {
    if (!confirm("Удалить подписку?")) {
        return;
    }
    await apiRequest(`/subscriptions/${subscriptionId}`, { method: "DELETE" });
    await loadSubscriptions();
});

window.togglePlan = (planId, isActive) => safeAction(async () => {
    const endpoint = isActive ? "deactivate" : "activate";
    await apiRequest(`/plans/${planId}/${endpoint}`, { method: "PATCH" });
    await loadPlans();
});

window.editPlan = (planId) => safeAction(async () => {
    const current = await apiRequest(`/plans/${planId}`);
    const plan = current.plan;
    const name = prompt("Название:", plan.name);
    if (!name) {
        return;
    }
    const durationDays = Number(prompt("Дней:", plan.duration_days));
    const priceUsd = Number(prompt("Цена USD:", plan.price_usd));
    const isTrial = confirm("Это trial план?");
    const isActive = confirm("План активен?");
    await apiRequest(`/plans/${planId}`, {
        method: "PUT",
        body: JSON.stringify({
            name,
            duration_days: durationDays,
            price_usd: priceUsd,
            is_trial: isTrial,
            is_active: isActive,
        }),
    });
    await loadPlans();
});

window.deletePlan = (planId) => safeAction(async () => {
    if (!confirm("Удалить тариф?")) {
        return;
    }
    await apiRequest(`/plans/${planId}`, { method: "DELETE" });
    await loadPlans();
});

window.editPayment = (paymentId) => safeAction(async () => {
    const current = await apiRequest(`/payments/${paymentId}`);
    const p = current.payment;
    const amountUsd = Number(prompt("Сумма USD:", p.amount_usd));
    const statusValue = prompt(
        "Статус (created|success|paid|expired|cancelled):",
        p.status
    );
    const nodeIdRaw = prompt("Node ID (пусто = null):", p.node_id ?? "");
    const accessType = prompt("Тип (mtproto|socks5):", p.access_type || "mtproto");
    const nodeId = nodeIdRaw === "" ? null : Number(nodeIdRaw);
    await apiRequest(`/payments/${paymentId}`, {
        method: "PUT",
        body: JSON.stringify({
            amount_usd: amountUsd,
            status: statusValue,
            node_id: nodeId,
            access_type: accessType,
        }),
    });
    await loadPayments();
});

window.deletePayment = (paymentId) => safeAction(async () => {
    if (!confirm("Удалить платёж?")) {
        return;
    }
    await apiRequest(`/payments/${paymentId}`, { method: "DELETE" });
    await loadPayments();
});

function setupEvents() {
    document.getElementById("logout-btn").addEventListener("click", () => {
        state.token = "";
        localStorage.removeItem(TOKEN_KEY);
        if (state.nodesPollTimer) {
            clearInterval(state.nodesPollTimer);
            state.nodesPollTimer = null;
        }
        setAuthState();
    });

    document.getElementById("password-login-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const username = document.getElementById("login-username").value;
        const password = document.getElementById("login-password").value;
        try {
            const data = await apiRequest("/login", {
                method: "POST",
                body: JSON.stringify({ username, password }),
            });
            state.token = data.access_token;
            localStorage.setItem(TOKEN_KEY, state.token);
            await onAuthorized();
        } catch (error) {
            alert(`Ошибка входа: ${error.message}`);
        }
    });

    document.getElementById("users-refresh").addEventListener("click", () => loadUsers().catch(console.error));
    document.getElementById("users-search").addEventListener("input", () => loadUsers().catch(console.error));
    document.getElementById("nodes-refresh").addEventListener("click", () => loadNodes().catch(console.error));
    document.getElementById("subs-refresh").addEventListener("click", () => loadSubscriptions().catch(console.error));
    document.getElementById("subs-status-filter").addEventListener("change", () => loadSubscriptions().catch(console.error));
    document.getElementById("payments-refresh").addEventListener("click", () => loadPayments().catch(console.error));
    document.getElementById("plans-refresh").addEventListener("click", () => loadPlans().catch(console.error));

    document.getElementById("node-create-btn").addEventListener("click", async () => {
        const name = prompt("Имя ноды:", "");
        const host = prompt("Host:", "");
        const country = prompt("Country:", "");
        const countryFlag = prompt("Country flag:", "");
        const agentUrl = prompt("Agent URL (http://IP:9090):", "");
        const agentApiKey = prompt("Agent API key:", "");
        if (!name || !host || !country || !agentUrl || !agentApiKey) {
            return;
        }
        await apiRequest("/nodes", {
            method: "POST",
            body: JSON.stringify({
                name,
                host,
                port: 443,
                country,
                country_flag: countryFlag,
                agent_url: agentUrl,
                agent_api_key: agentApiKey,
                max_users: 500,
                socks5_port: 1080,
            }),
        });
        await loadNodes();
    });

    document.getElementById("plan-create-btn").addEventListener("click", async () => {
        const name = prompt("Название тарифа:", "");
        const durationDays = Number(prompt("Длительность в днях:", "30"));
        const priceUsd = Number(prompt("Цена USD:", "3"));
        if (!name || !durationDays) {
            return;
        }
        await apiRequest("/plans", {
            method: "POST",
            body: JSON.stringify({
                name,
                duration_days: durationDays,
                price_usd: priceUsd,
                is_trial: false,
                is_active: true,
            }),
        });
        await loadPlans();
    });
}

async function bootstrap() {
    setupTabs();
    setupEvents();
    setAuthState();
    try {
        await loadAuthConfig();
    } catch (error) {
        console.error(error);
    }
    if (state.token) {
        try {
            await onAuthorized();
        } catch (error) {
            state.token = "";
            localStorage.removeItem(TOKEN_KEY);
            setAuthState();
            alert(`Сессия истекла: ${error.message}`);
        }
    }
}

bootstrap().catch((error) => {
    console.error(error);
    alert(`Ошибка загрузки админки: ${error.message}`);
});
