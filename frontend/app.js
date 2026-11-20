const API_BASE =
  window.location.protocol === "file:" ? "http://localhost:5000" : window.location.origin;

const state = {
  token: sessionStorage.getItem("smart_lab_token") || null,
  user: JSON.parse(sessionStorage.getItem("smart_lab_user") || "null"),
  labs: [],
  components: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function showToast(message, type = "success") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast ${type}`;
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => toast.classList.add("hidden"), 3500);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && state.token) {
      logout();
    }
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function openModal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $("#modal-backdrop").classList.remove("hidden");
}

function closeModal() {
  $("#modal-backdrop").classList.add("hidden");
}

function saveSession(token, user) {
  state.token = token;
  state.user = user;
  sessionStorage.setItem("smart_lab_token", token);
  sessionStorage.setItem("smart_lab_user", JSON.stringify(user));
}

function logout() {
  state.token = null;
  state.user = null;
  sessionStorage.removeItem("smart_lab_token");
  sessionStorage.removeItem("smart_lab_user");
  renderAppState();
}

function isRole(...roles) {
  return state.user && roles.includes(state.user.role);
}

function renderAppState() {
  const loggedIn = Boolean(state.token && state.user);
  $("#auth-view").classList.toggle("hidden", loggedIn);
  $("#app-view").classList.toggle("hidden", !loggedIn);
  $("#user-controls").classList.toggle("hidden", !loggedIn);

  if (!loggedIn) return;

  $("#user-name-label").textContent = state.user.name;
  $("#user-role-pill").textContent = state.user.role;

  $$(".staff-only").forEach((el) =>
    el.classList.toggle("hidden", !isRole("faculty", "incharge", "admin"))
  );
  $$(".incharge-only").forEach((el) =>
    el.classList.toggle("hidden", !isRole("incharge", "admin"))
  );
  $$(".admin-only").forEach((el) => el.classList.toggle("hidden", !isRole("admin")));

  switchSection("catalog");
}

function switchSection(sectionId) {
  $$(".nav-btn").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.section === sectionId)
  );
  $$(".section").forEach((sec) =>
    sec.classList.toggle("hidden", sec.id !== `section-${sectionId}`)
  );

  if (sectionId === "catalog") loadCatalog();
  if (sectionId === "my-issues") loadMyIssues();
  if (sectionId === "manage-issues") loadManageIssues();
  if (sectionId === "reports") loadReports();
  if (sectionId === "users") loadUsers();
}

async function loadLabs() {
  const data = await api("/catalog/labs");
  state.labs = data.labs || [];
  const select = $("#catalog-lab-filter");
  const current = select.value;
  select.innerHTML =
    `<option value="">All Labs</option>` +
    state.labs
      .map((l) => `<option value="${l.id}">${escapeHtml(l.name)}</option>`)
      .join("");
  select.value = current;
}

async function loadCatalog() {
  try {
    await loadLabs();
    const params = new URLSearchParams();
    const q = $("#catalog-search").value.trim();
    const labId = $("#catalog-lab-filter").value;
    const avail = $("#catalog-avail-filter").value;
    if (q) params.set("q", q);
    if (labId) params.set("lab_id", labId);
    if (avail) params.set("available", avail);

    const data = await api(`/catalog/components?${params.toString()}`);
    state.components = data.components || [];
    renderCatalogGrid();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function renderCatalogGrid() {
  const grid = $("#catalog-grid");
  if (!state.components.length) {
    grid.innerHTML = `<div class="card muted">No components match your current filters.</div>`;
    return;
  }

  grid.innerHTML = state.components
    .map((c) => {
      const pct = c.total_quantity ? Math.round((c.available_quantity / c.total_quantity) * 100) : 0;
      const fillClass =
        c.available_quantity === 0 ? "empty" : c.available_quantity <= 5 ? "low" : "";

      const manageBtns = isRole("incharge", "admin")
        ? `<button class="btn btn-secondary btn-sm" onclick="openEditComponentModal(${c.id})">Edit</button>`
        : "";
      const deleteBtn = isRole("admin")
        ? `<button class="btn btn-danger btn-sm" onclick="deleteComponent(${c.id})">Archive</button>`
        : "";

      return `
        <article class="card comp-card">
          <div>
            <div class="comp-top">
              <div>
                <div class="comp-title">${escapeHtml(c.name)}</div>
                <div class="comp-meta">${escapeHtml(c.lab_name)} &middot; ${escapeHtml(c.category)}</div>
              </div>
              <span class="pill">${c.available_quantity}/${c.total_quantity}</span>
            </div>
            ${c.description ? `<p class="muted" style="margin-top:0.5rem;">${escapeHtml(c.description)}</p>` : ""}
            <div class="stock-bar"><div class="stock-fill ${fillClass}" style="width:${pct}%"></div></div>
          </div>
          <div class="comp-actions">
            <button class="btn btn-primary btn-sm" ${c.available_quantity === 0 ? "disabled" : ""} onclick="openRequestModal(${c.id})">
              ${c.available_quantity === 0 ? "Out of Stock" : "Request"}
            </button>
            ${manageBtns}
            ${deleteBtn}
          </div>
        </article>
      `;
    })
    .join("");
}

window.openRequestModal = function (compId) {
  const c = state.components.find((item) => item.id === compId);
  if (!c) return;
  openModal(
    `Request: ${c.name}`,
    `
    <form id="request-comp-form" class="form">
      <p class="muted">Lab: <strong>${escapeHtml(c.lab_name)}</strong> &middot; Available: <strong>${c.available_quantity}</strong></p>
      <label>
        Quantity
        <input type="number" id="req-qty" min="1" max="${c.available_quantity}" value="1" required />
      </label>
      <label>
        Duration (days, 1-30)
        <input type="number" id="req-days" min="1" max="30" value="7" required />
      </label>
      <label>
        Purpose / Project Name
        <textarea id="req-purpose" rows="2" placeholder="e.g., IoT Mini Project"></textarea>
      </label>
      <button type="submit" class="btn btn-primary">Submit Request</button>
    </form>
  `
  );
  $("#request-comp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/issues/request", {
        method: "POST",
        body: JSON.stringify({
          component_id: compId,
          quantity: Number($("#req-qty").value),
          days: Number($("#req-days").value),
          purpose: $("#req-purpose").value.trim(),
        }),
      });
      closeModal();
      showToast("Component request submitted!");
      loadCatalog();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
};

function openAddLabModal() {
  openModal(
    "Add New Lab",
    `
    <form id="add-lab-form" class="form">
      <label>Lab Name <input type="text" id="lab-name" required placeholder="AI & Robotics Lab" /></label>
      <label>Location <input type="text" id="lab-location" placeholder="Block B, Floor 2" /></label>
      <button type="submit" class="btn btn-primary">Create Lab</button>
    </form>
  `
  );
  $("#add-lab-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/catalog/labs", {
        method: "POST",
        body: JSON.stringify({
          name: $("#lab-name").value.trim(),
          location: $("#lab-location").value.trim(),
        }),
      });
      closeModal();
      showToast("Lab created!");
      loadCatalog();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function openAddComponentModal() {
  const labOptions = state.labs
    .map((l) => `<option value="${l.id}">${escapeHtml(l.name)}</option>`)
    .join("");
  openModal(
    "Add Hardware Component",
    `
    <form id="add-comp-form" class="form">
      <label>Component Name <input type="text" id="comp-name" required placeholder="DHT11 Sensor" /></label>
      <label>Category <input type="text" id="comp-cat" value="Sensor" /></label>
      <label>Lab <select id="comp-lab" required>${labOptions}</select></label>
      <label>Total Quantity <input type="number" id="comp-total" min="0" value="10" required /></label>
      <label>Description <textarea id="comp-desc" rows="2"></textarea></label>
      <button type="submit" class="btn btn-primary">Add Component</button>
    </form>
  `
  );
  $("#add-comp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/catalog/components", {
        method: "POST",
        body: JSON.stringify({
          name: $("#comp-name").value.trim(),
          category: $("#comp-cat").value.trim(),
          lab_id: Number($("#comp-lab").value),
          total_quantity: Number($("#comp-total").value),
          description: $("#comp-desc").value.trim(),
        }),
      });
      closeModal();
      showToast("Component added!");
      loadCatalog();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

window.openEditComponentModal = function (compId) {
  const c = state.components.find((item) => item.id === compId);
  if (!c) return;
  const labOptions = state.labs
    .map(
      (l) =>
        `<option value="${l.id}" ${l.id === c.lab_id ? "selected" : ""}>${escapeHtml(l.name)}</option>`
    )
    .join("");
  openModal(
    `Edit: ${c.name}`,
    `
    <form id="edit-comp-form" class="form">
      <label>Name <input type="text" id="edit-name" value="${escapeHtml(c.name)}" required /></label>
      <label>Category <input type="text" id="edit-cat" value="${escapeHtml(c.category)}" /></label>
      <label>Lab <select id="edit-lab">${labOptions}</select></label>
      <label>Total Quantity <input type="number" id="edit-total" min="0" value="${c.total_quantity}" required /></label>
      <label>Available Quantity <input type="number" id="edit-avail" min="0" value="${c.available_quantity}" required /></label>
      <label>Description <textarea id="edit-desc" rows="2">${escapeHtml(c.description || "")}</textarea></label>
      <button type="submit" class="btn btn-primary">Save Changes</button>
    </form>
  `
  );
  $("#edit-comp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/catalog/components/${compId}`, {
        method: "PUT",
        body: JSON.stringify({
          name: $("#edit-name").value.trim(),
          category: $("#edit-cat").value.trim(),
          lab_id: Number($("#edit-lab").value),
          total_quantity: Number($("#edit-total").value),
          available_quantity: Number($("#edit-avail").value),
          description: $("#edit-desc").value.trim(),
        }),
      });
      closeModal();
      showToast("Component updated!");
      loadCatalog();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
};

window.deleteComponent = async function (compId) {
  if (!confirm("Archive or delete this component?")) return;
  try {
    const res = await api(`/catalog/components/${compId}`, { method: "DELETE" });
    showToast(res.message);
    loadCatalog();
  } catch (err) {
    showToast(err.message, "error");
  }
};

async function loadMyIssues() {
  try {
    const status = $("#my-issues-status-filter").value;
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    const data = await api(`/issues/my${qs}`);
    const tbody = $("#my-issues-tbody");
    if (!data.issues.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">No requests found.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.issues
      .map(
        (i) => `
      <tr>
        <td>#${i.id}</td>
        <td><strong>${escapeHtml(i.component_name)}</strong></td>
        <td>${escapeHtml(i.lab_name)}</td>
        <td>${i.quantity}</td>
        <td>${escapeHtml(i.request_date || i.issue_date || "-")}</td>
        <td>${escapeHtml(i.due_date || `${i.requested_days}d est.`)}</td>
        <td>
          <span class="pill pill-${i.status}">${i.status}</span>
          ${i.is_overdue ? `<span class="pill pill-overdue">Overdue ${i.days_overdue}d</span>` : ""}
        </td>
        <td class="muted">${escapeHtml(i.condition_note || i.purpose || "-")}</td>
      </tr>
    `
      )
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadManageIssues() {
  try {
    const status = $("#manage-status-filter").value;
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    const data = await api(`/issues${qs}`);
    const tbody = $("#manage-issues-tbody");
    if (!data.issues.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">No issue records in this view.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.issues
      .map((i) => {
        const btns = [];
        if (i.status === "pending") {
          btns.push(`<button class="btn btn-primary btn-sm" onclick="approveIssue(${i.id})">Approve</button>`);
          btns.push(`<button class="btn btn-danger btn-sm" onclick="rejectIssue(${i.id})">Reject</button>`);
        }
        if ((i.status === "approved" || i.status === "pending") && isRole("incharge", "admin")) {
          btns.push(`<button class="btn btn-success btn-sm" onclick="handoverIssue(${i.id})">Issue</button>`);
        }
        if (i.status === "issued" && isRole("incharge", "admin")) {
          btns.push(`<button class="btn btn-warning btn-sm" onclick="openReturnModal(${i.id}, ${i.quantity})">Return</button>`);
        }
        return `
          <tr>
            <td>#${i.id}</td>
            <td>
              <strong>${escapeHtml(i.user_name)}</strong><br />
              <span class="muted">${escapeHtml(i.enrollment_no || i.user_email)}</span>
            </td>
            <td>${escapeHtml(i.component_name)}<br /><span class="muted">${escapeHtml(i.lab_name)}</span></td>
            <td>${i.quantity}</td>
            <td class="muted">${escapeHtml(i.purpose || "-")}</td>
            <td class="muted">
              Req: ${escapeHtml(i.request_date || "-")}<br />
              Due: ${escapeHtml(i.due_date || "-")}
            </td>
            <td>
              <span class="pill pill-${i.status}">${i.status}</span>
              ${i.is_overdue ? `<span class="pill pill-overdue">Overdue ${i.days_overdue}d</span>` : ""}
            </td>
            <td><div class="comp-actions">${btns.join("") || "-"}</div></td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.approveIssue = async function (id) {
  try {
    await api(`/issues/${id}/approve`, { method: "POST", body: JSON.stringify({}) });
    showToast(`Request #${id} approved`);
    loadManageIssues();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.rejectIssue = async function (id) {
  const reason = prompt("Optional rejection reason:") || "";
  try {
    await api(`/issues/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast(`Request #${id} rejected`);
    loadManageIssues();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.handoverIssue = async function (id) {
  try {
    await api(`/issues/${id}/issue`, { method: "POST", body: JSON.stringify({}) });
    showToast(`Component handed out for #${id}`);
    loadManageIssues();
  } catch (err) {
    showToast(err.message, "error");
  }
};

window.openReturnModal = function (id, qty) {
  openModal(
    `Record Return (#${id})`,
    `
    <form id="return-form" class="form">
      <label>
        Condition Status
        <select id="ret-condition">
          <option value="intact">Intact (Full Restock)</option>
          <option value="damaged">Damaged (No Restock by Default)</option>
          <option value="missing">Missing (No Restock)</option>
        </select>
      </label>
      <label>
        Units to Restock (0 - ${qty})
        <input type="number" id="ret-restock" min="0" max="${qty}" value="${qty}" required />
      </label>
      <label>
        Condition Notes
        <textarea id="ret-note" rows="2" placeholder="Optional inspection notes"></textarea>
      </label>
      <button type="submit" class="btn btn-success">Confirm Return</button>
    </form>
  `
  );
  $("#ret-condition").addEventListener("change", (e) => {
    $("#ret-restock").value = e.target.value === "intact" ? qty : 0;
  });
  $("#return-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/issues/${id}/return`, {
        method: "POST",
        body: JSON.stringify({
          condition_status: $("#ret-condition").value,
          restock_quantity: Number($("#ret-restock").value),
          condition_note: $("#ret-note").value.trim(),
        }),
      });
      closeModal();
      showToast(`Return recorded for #${id}`);
      loadManageIssues();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
};

async function loadReports() {
  try {
    const [summary, overdue] = await Promise.all([
      api("/reports/summary"),
      api("/reports/overdue"),
    ]);

    const o = summary.overview;
    const kpis = [
      ["Total Labs", o.total_labs],
      ["Component Types", o.total_component_types],
      ["Available Units", `${o.available_units} / ${o.total_units}`],
      ["Issued Units", o.currently_issued_units],
      ["Pending Requests", o.pending_requests],
      ["Overdue Items", o.overdue_count],
    ];
    $("#kpi-grid").innerHTML = kpis
      .map(
        ([label, val]) => `
      <div class="kpi-card">
        <div class="kpi-label">${label}</div>
        <div class="kpi-value">${val}</div>
      </div>
    `
      )
      .join("");

    $("#low-stock-tbody").innerHTML = summary.low_stock_items.length
      ? summary.low_stock_items
          .map(
            (i) => `
          <tr>
            <td>${escapeHtml(i.name)}</td>
            <td>${escapeHtml(i.lab_name)}</td>
            <td><strong>${i.available_quantity}</strong> / ${i.total_quantity}</td>
          </tr>
        `
          )
          .join("")
      : `<tr><td colspan="3" class="muted">No low-stock components.</td></tr>`;

    $("#overdue-tbody").innerHTML = overdue.overdue.length
      ? overdue.overdue
          .map(
            (i) => `
          <tr>
            <td>${escapeHtml(i.user_name)}<br /><span class="muted">${escapeHtml(i.enrollment_no || i.user_email)}</span></td>
            <td>${escapeHtml(i.component_name)}</td>
            <td>${i.quantity}</td>
            <td>${escapeHtml(i.due_date)}</td>
            <td><span class="pill pill-overdue">${i.days_overdue}d</span></td>
          </tr>
        `
          )
          .join("")
      : `<tr><td colspan="5" class="muted">No overdue items.</td></tr>`;

    if (isRole("incharge", "admin")) {
      const logData = await api("/reports/activity-log?limit=30");
      $("#activity-tbody").innerHTML = logData.logs.length
        ? logData.logs
            .map(
              (l) => `
            <tr>
              <td class="muted">${escapeHtml(l.created_at)}</td>
              <td>${escapeHtml(l.actor_name || "System")} <span class="pill">${escapeHtml(l.actor_role || "-")}</span></td>
              <td><code>${escapeHtml(l.action)}</code></td>
              <td>${escapeHtml(l.details || "-")}</td>
            </tr>
          `
            )
            .join("")
        : `<tr><td colspan="4" class="muted">No activity recorded yet.</td></tr>`;
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function loadUsers() {
  try {
    const data = await api("/auth/users");
    $("#users-tbody").innerHTML = data.users
      .map(
        (u) => `
      <tr>
        <td>#${u.id}</td>
        <td><strong>${escapeHtml(u.name)}</strong></td>
        <td>${escapeHtml(u.email)}</td>
        <td>${escapeHtml(u.enrollment_no || "-")}</td>
        <td><span class="pill">${escapeHtml(u.role)}</span></td>
        <td>
          <select onchange="updateUserRole(${u.id}, this.value)">
            ${["student", "faculty", "incharge", "admin"]
              .map((r) => `<option value="${r}" ${r === u.role ? "selected" : ""}>${r}</option>`)
              .join("")}
          </select>
        </td>
      </tr>
    `
      )
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

window.updateUserRole = async function (userId, role) {
  try {
    await api(`/auth/users/${userId}/role`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    });
    showToast("User role updated!");
    loadUsers();
  } catch (err) {
    showToast(err.message, "error");
  }
};

$$("[data-auth-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.authTab;
    $$("[data-auth-tab]").forEach((b) => b.classList.toggle("active", b === btn));
    $("#login-form").classList.toggle("hidden", tab !== "login");
    $("#register-form").classList.toggle("hidden", tab !== "register");
  });
});

$$("[data-demo]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const [email, password] = btn.dataset.demo.split("|");
    $("#login-email").value = email;
    $("#login-password").value = password;
    $("#login-form").requestSubmit();
  });
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: $("#login-email").value.trim(),
        password: $("#login-password").value,
      }),
    });
    saveSession(data.access_token, data.user);
    showToast(`Welcome back, ${data.user.name}!`);
    renderAppState();
  } catch (err) {
    showToast(err.message, "error");
  }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        name: $("#reg-name").value.trim(),
        email: $("#reg-email").value.trim(),
        enrollment_no: $("#reg-enroll").value.trim() || null,
        role: $("#reg-role").value,
        password: $("#reg-password").value,
      }),
    });
    showToast("Account created! You can sign in now.");
    $('[data-auth-tab="login"]').click();
    $("#login-email").value = $("#reg-email").value.trim();
  } catch (err) {
    showToast(err.message, "error");
  }
});

$("#logout-btn").addEventListener("click", logout);
$("#modal-close-btn").addEventListener("click", closeModal);
$("#modal-backdrop").addEventListener("click", (e) => {
  if (e.target === $("#modal-backdrop")) closeModal();
});

$$(".nav-btn").forEach((btn) =>
  btn.addEventListener("click", () => switchSection(btn.dataset.section))
);

$("#catalog-search").addEventListener("input", loadCatalog);
$("#catalog-lab-filter").addEventListener("change", loadCatalog);
$("#catalog-avail-filter").addEventListener("change", loadCatalog);
$("#catalog-refresh-btn").addEventListener("click", loadCatalog);
$("#open-lab-modal-btn").addEventListener("click", openAddLabModal);
$("#open-comp-modal-btn").addEventListener("click", openAddComponentModal);

$("#my-issues-status-filter").addEventListener("change", loadMyIssues);
$("#manage-status-filter").addEventListener("change", loadManageIssues);
$("#refresh-reports-btn").addEventListener("click", loadReports);

renderAppState();
