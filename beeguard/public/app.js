const $ = id => document.getElementById(id);

async function api(path, options = {}) {
    const response = await fetch(path, {
        headers: {
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {})
        },
        ...options
    });

    const text = await response.text();

    let data;
    try {
        data = text ? JSON.parse(text) : {};
    } catch {
        throw new Error("Invalid response from server");
    }

    if (!response.ok) {
        throw new Error(data.error || data.message || "Request failed");
    }

    return data;
}

/* =========================
   SERVER STATUS
========================= */

async function checkServer() {
    const status = $("serverStatus");

    if (!status) return;

    try {
        await api("/api/health");

        status.textContent = "● Server Online";
        status.classList.add("online");
        status.classList.remove("offline");
    } catch {
        status.textContent = "● Server Offline";
        status.classList.add("offline");
        status.classList.remove("online");
    }
}

/* =========================
   DASHBOARD
========================= */

async function loadDashboard() {
    try {
        const data = await api("/api/dashboard");

        if ($("beeHealth"))
            $("beeHealth").textContent =
                data.beeHealth ?? data.bee_health ?? "--";

        if ($("pollination"))
            $("pollination").textContent =
                data.pollination ?? data.pollinationArea ?? "--";

        if ($("riskValue"))
            $("riskValue").textContent =
                data.riskValue ?? data.risk ?? "--";

        if ($("honeyBatches"))
            $("honeyBatches").textContent =
                data.honeyBatches ?? data.honey_batches ?? "--";

    } catch (error) {
        console.error("Dashboard:", error);
    }
}

/* =========================
   PESTICIDE ALERTS
========================= */

async function loadAlerts() {
    const container = $("alertsContainer");

    if (!container) return;

    try {
        const data = await api("/api/alerts?status=active");

        const alerts = data.alerts || data || [];

        if (!alerts.length) {
            container.innerHTML = `
                <div class="result-card">
                    <strong>No active pesticide alerts</strong>
                    <p>No active alerts found.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = alerts.map(alert => `
            <div class="result-card">
                <h3>${escapeHtml(
                    alert.crop_name || alert.crop || "Crop Alert"
                )}</h3>

                <p>
                    <strong>Location:</strong>
                    ${escapeHtml(alert.location || "Unknown")}
                </p>

                <p>
                    <strong>Risk:</strong>
                    ${escapeHtml(
                        alert.risk_level ||
                        alert.risk ||
                        "Unknown"
                    )}
                </p>

                <button
                    class="primary-button protect-button"
                    data-alert-id="${alert.id}">
                    Protect Hive
                </button>
            </div>
        `).join("");

        document.querySelectorAll(".protect-button")
            .forEach(button => {
                button.addEventListener("click", () => {
                    protectHive(button.dataset.alertId);
                });
            });

    } catch (error) {
        container.innerHTML = `
            <div class="result-card">
                <strong>Unable to load alerts</strong>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

async function protectHive(id) {
    try {
        const data = await api(`/api/alerts/${id}/protect`, {
            method: "POST"
        });

        alert(data.message || "Hive protection activated.");

        loadAlerts();
        loadDashboard();

    } catch (error) {
        alert(error.message);
    }
}

/* =========================
   HIVE MATCHING
========================= */

async function submitMatch(event) {
    event.preventDefault();

    const result = $("matchResult");

    if (!result) return;

    const form = event.target;

    const payload = {
        crop: form.crop?.value || "",
        location: form.location?.value || "",
        hive_count: Number(form.hive_count?.value || 1)
    };

    result.innerHTML = "<p>Finding suitable hives...</p>";

    try {
        const data = await api("/api/matches", {
            method: "POST",
            body: JSON.stringify(payload)
        });

        const matches = data.matches || data || [];

        if (!matches.length) {
            result.innerHTML = `
                <div class="result-card">
                    <strong>No suitable hives found.</strong>
                </div>
            `;
            return;
        }

        result.innerHTML = matches.map(match => `
            <div class="result-card">
                <h3>${escapeHtml(
                    match.hive_name ||
                    match.name ||
                    "Hive"
                )}</h3>

                <p>
                    <strong>Location:</strong>
                    ${escapeHtml(match.location || "Unknown")}
                </p>

                <p>
                    <strong>Distance:</strong>
                    ${escapeHtml(
                        String(
                            match.distance_km ??
                            match.distance ??
                            "N/A"
                        )
                    )} km
                </p>

                <p>
                    <strong>Compatibility:</strong>
                    ${escapeHtml(
                        String(
                            match.compatibility ??
                            match.score ??
                            "N/A"
                        )
                    )}
                </p>
            </div>
        `).join("");

    } catch (error) {
        result.innerHTML = `
            <div class="result-card">
                <strong>Matching failed</strong>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

/* =========================
   HONEY VERIFICATION
========================= */

async function verifyHoney(event) {
    event.preventDefault();

    const batchId = $("batchId")?.value.trim();
    const result = $("honeyResult");

    if (!batchId || !result) return;

    result.innerHTML = "<p>Verifying honey batch...</p>";

    try {
        const data = await api(
            `/api/honey/batch/${encodeURIComponent(batchId)}`
        );

        result.innerHTML = `
            <div class="result-card">
                <h3>🍯 Honey Verified</h3>

                <p>
                    <strong>Batch ID:</strong>
                    ${escapeHtml(data.batch_id || batchId)}
                </p>

                <p>
                    <strong>Honey Type:</strong>
                    ${escapeHtml(
                        data.honey_type ||
                        data.honeyType ||
                        "Unknown"
                    )}
                </p>

                <p>
                    <strong>Origin:</strong>
                    ${escapeHtml(data.origin || "Unknown")}
                </p>

                <p>
                    <strong>Quality:</strong>
                    ${escapeHtml(
                        data.quality_status ||
                        data.quality ||
                        "Unknown"
                    )}
                </p>

                <p>
                    <strong>Status:</strong>
                    ${escapeHtml(
                        data.status || "Verified"
                    )}
                </p>
            </div>
        `;

    } catch (error) {
        result.innerHTML = `
            <div class="result-card">
                <strong>Verification failed</strong>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

/* =========================
   BUYER SEARCH
========================= */

async function findAffordableHoney(event) {
    if (event) event.preventDefault();

    const type = $("honeyType")?.value || "";
    const maxPrice = $("maxPrice")?.value || "";
    const result = $("buyerResults");

    if (!result) return;

    result.innerHTML = "<p>Searching honey...</p>";

    try {
        let url = "/api/buyer/search";

        const params = new URLSearchParams();

        if (type)
            params.set("type", type);

        if (maxPrice)
            params.set("maxPrice", maxPrice);

        const query = params.toString();

        if (query)
            url += `?${query}`;

        const data = await api(url);

        const products =
            data.results ||
            data.products ||
            data.honey ||
            data ||
            [];

        if (!Array.isArray(products) || !products.length) {
            result.innerHTML = `
                <div class="result-card">
                    <strong>No honey products found.</strong>
                </div>
            `;
            return;
        }

        result.innerHTML = products.map(item => `
            <div class="result-card">
                <h3>
                    🍯 ${escapeHtml(
                        item.honey_type ||
                        item.honeyType ||
                        item.type ||
                        "Honey"
                    )}
                </h3>

                <p>
                    <strong>Seller:</strong>
                    ${escapeHtml(
                        item.seller_name ||
                        item.seller ||
                        "Unknown"
                    )}
                </p>

                <p>
                    <strong>Origin:</strong>
                    ${escapeHtml(item.origin || "Unknown")}
                </p>

                <p>
                    <strong>Price:</strong>
                    ₹${escapeHtml(
                        String(
                            item.price_per_kg ??
                            item.price ??
                            "N/A"
                        )
                    )}/kg
                </p>

                <p>
                    <strong>Quantity:</strong>
                    ${escapeHtml(
                        String(
                            item.quantity_kg ??
                            item.quantity ??
                            "N/A"
                        )
                    )} kg
                </p>
            </div>
        `).join("");

    } catch (error) {
        result.innerHTML = `
            <div class="result-card">
                <strong>Search failed</strong>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

/* =====================================================
   🍯 HONEY AVAILABILITY
===================================================== */

async function searchHoneyAvailability(event) {
    if (event) event.preventDefault();

    const input = $("availabilityType");
    const result = $("availabilityResults");

    if (!result) return;

    const type =
        input?.value.trim() || "Wildflower";

    result.innerHTML =
        "<p>Checking honey availability...</p>";

    try {
        const data = await api(
            `/api/honey/availability?type=${encodeURIComponent(type)}`
        );

        renderAvailability(data);

    } catch (error) {
        result.innerHTML = `
            <div class="result-card">
                <strong>Unable to check availability</strong>
                <p>${escapeHtml(error.message)}</p>
            </div>
        `;
    }
}

function renderAvailability(data) {
    const result = $("availabilityResults");

    if (!result) return;

    const batches =
        data.results ||
        data.batches ||
        [];

    const total =
        data.availableQuantity ??
        data.available_quantity ??
        batches.reduce((sum, item) => {
            return sum + Number(
                item.quantity_kg ??
                item.available_quantity ??
                item.quantity ??
                0
            );
        }, 0);

    const type =
        data.honeyType ||
        data.honey_type ||
        $("availabilityType")?.value ||
        "Honey";

    if (!batches.length) {
        result.innerHTML = `
            <div class="result-card">
                <h3>🍯 ${escapeHtml(type)}</h3>

                <p>
                    No honey currently available
                    for this type.
                </p>

                <strong>Available: 0 kg</strong>
            </div>
        `;
        return;
    }

    result.innerHTML = `
        <div class="availability-summary">
            <h3>🍯 ${escapeHtml(type)}</h3>

            <div class="availability-number">
                ${escapeHtml(String(total))} kg
            </div>

            <p>
                Total honey currently available
            </p>
        </div>

        <div class="availability-grid">

            ${batches.map(batch => `
                <div class="result-card">

                    <h3>
                        ${escapeHtml(
                            batch.honey_type ||
                            batch.honeyType ||
                            type
                        )}
                    </h3>

                    <p>
                        <strong>Batch:</strong>
                        ${escapeHtml(
                            batch.batch_id ||
                            batch.id ||
                            "N/A"
                        )}
                    </p>

                    <p>
                        <strong>Seller:</strong>
                        ${escapeHtml(
                            batch.seller_name ||
                            batch.seller ||
                            "Unknown"
                        )}
                    </p>

                    <p>
                        <strong>Origin:</strong>
                        ${escapeHtml(
                            batch.origin ||
                            batch.location ||
                            "Unknown"
                        )}
                    </p>

                    <p>
                        <strong>Quantity:</strong>
                        ${escapeHtml(
                            String(
                                batch.quantity_kg ??
                                batch.available_quantity ??
                                batch.quantity ??
                                0
                            )
                        )} kg
                    </p>

                    <p>
                        <strong>Price:</strong>
                        ₹${escapeHtml(
                            String(
                                batch.price_per_kg ??
                                batch.price ??
                                "N/A"
                            )
                        )}/kg
                    </p>

                    <p>
                        <strong>Quality:</strong>
                        ${escapeHtml(
                            batch.quality_status ||
                            batch.quality ||
                            "Verified"
                        )}
                    </p>

                </div>
            `).join("")}

        </div>
    `;
}

/* =====================================================
   🐝 HIVE OCCUPANCY
===================================================== */

async function loadHiveOccupancy() {
    try {
        const data =
            await api("/api/hives/occupancy");

        renderHiveOccupancy(data);

    } catch (error) {
        console.error(
            "Hive occupancy:",
            error
        );

        const list = $("hiveList");

        if (list) {
            list.innerHTML = `
                <div class="result-card">
                    <strong>
                        Unable to load hive occupancy
                    </strong>

                    <p>
                        ${escapeHtml(error.message)}
                    </p>
                </div>
            `;
        }
    }
}

function renderHiveOccupancy(data) {

    const total =
        Number(
            data.total ??
            data.totalHives ??
            0
        );

    const occupied =
        Number(
            data.occupied ??
            data.occupiedHives ??
            0
        );

    const available =
        Number(
            data.available ??
            data.availableHives ??
            0
        );

    const maintenance =
        Number(
            data.maintenance ??
            data.maintenanceHives ??
            0
        );

    const percent =
        Number(
            data.occupancyPercent ??
            data.occupancy_percentage ??
            (total
                ? (occupied / total) * 100
                : 0)
        );

    if ($("totalHives"))
        $("totalHives").textContent = total;

    if ($("occupiedHives"))
        $("occupiedHives").textContent = occupied;

    if ($("availableHives"))
        $("availableHives").textContent = available;

    if ($("maintenanceHives"))
        $("maintenanceHives").textContent =
            maintenance;

    if ($("occupancyProgress")) {
        $("occupancyProgress").style.width =
            `${Math.min(
                100,
                Math.max(0, percent)
            )}%`;
    }

    if ($("occupancyText")) {
        $("occupancyText").textContent =
            `${percent.toFixed(1)}% of hives are currently occupied`;
    }

    const list = $("hiveList");

    if (!list) return;

    const hives =
        data.hives || [];

    if (!hives.length) {
        list.innerHTML = `
            <div class="result-card">
                <p>
                    No hive data available.
                </p>
            </div>
        `;
        return;
    }

    list.innerHTML = hives.map(hive => {

        const status =
            String(
                hive.status ||
                "available"
            ).toLowerCase();

        let statusClass = "available";

        if (status.includes("occupied"))
            statusClass = "occupied";

        if (status.includes("maintenance"))
            statusClass = "maintenance";

        return `
            <div class="hive-card">

                <div>
                    <h3>
                        🐝 ${escapeHtml(
                            hive.hive_name ||
                            hive.name ||
                            "Hive"
                        )}
                    </h3>

                    <p>
                        ${escapeHtml(
                            hive.location ||
                            "Location unavailable"
                        )}
                    </p>

                    <p>
                        <strong>Bees:</strong>
                        ${escapeHtml(
                            String(
                                hive.bee_count ??
                                hive.beeCount ??
                                0
                            )
                        )}
                    </p>
                </div>

                <span class="
                    hive-status
                    ${statusClass}
                ">
                    ${escapeHtml(
                        hive.status ||
                        "Available"
                    )}
                </span>

            </div>
        `;
    }).join("");
}

/* =====================================================
   🤖 OFFLINE CHATBOT
===================================================== */

async function askBeeGuard(event) {
    if (event)
        event.preventDefault();

    const input =
        $("chatQuestion");

    const chatBox =
        $("chatBox");

    if (!input || !chatBox)
        return;

    const question =
        input.value.trim();

    if (!question)
        return;

    addChatMessage(
        question,
        "user"
    );

    input.value = "";

    addChatMessage(
        "Thinking...",
        "bot",
        "typing"
    );

    try {

        const data =
            await api("/api/chatbot", {
                method: "POST",

                body: JSON.stringify({
                    question: question
                })
            });

        removeTypingMessage();

        addChatMessage(
            data.answer ||
            data.response ||
            "I don't have an answer for that question.",
            "bot"
        );

    } catch (error) {

        removeTypingMessage();

        addChatMessage(
            "Sorry, I couldn't process that question.",
            "bot"
        );

        console.error(
            "Chatbot:",
            error
        );
    }
}

function addChatMessage(
    message,
    type,
    extraClass = ""
) {
    const chatBox =
        $("chatBox");

    if (!chatBox)
        return;

    const div =
        document.createElement("div");

    div.className =
        `chat-message ${type} ${extraClass}`;

    div.textContent =
        message;

    chatBox.appendChild(div);

    chatBox.scrollTop =
        chatBox.scrollHeight;
}

function removeTypingMessage() {
    const typing =
        document.querySelector(
            ".chat-message.typing"
        );

    if (typing)
        typing.remove();
}

/* =====================================================
   QUICK CHAT QUESTIONS
===================================================== */

function setupQuickQuestions() {

    document
        .querySelectorAll(".quick-question")
        .forEach(button => {

            button.addEventListener(
                "click",
                () => {

                    const question =
                        button.dataset.question ||
                        button.textContent.trim();

                    const input =
                        $("chatQuestion");

                    if (!input)
                        return;

                    input.value =
                        question;

                    input.focus();
                }
            );
        });
}

/* =====================================================
   HTML ESCAPE
===================================================== */

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/* =====================================================
   START
===================================================== */

async function start() {

    checkServer();

    loadDashboard();

    loadAlerts();

    loadHiveOccupancy();

    const availabilityForm =
        $("availabilityForm");

    if (availabilityForm) {

        availabilityForm.addEventListener(
            "submit",
            searchHoneyAvailability
        );

        searchHoneyAvailability();
    }

    const chatForm =
        $("chatForm");

    if (chatForm) {

        chatForm.addEventListener(
            "submit",
            askBeeGuard
        );

        setupQuickQuestions();
    }

    const verifyForm =
        $("verifyForm");

    if (verifyForm) {

        verifyForm.addEventListener(
            "submit",
            verifyHoney
        );
    }

    const buyerForm =
        $("buyerForm");

    if (buyerForm) {

        buyerForm.addEventListener(
            "submit",
            findAffordableHoney
        );

        findAffordableHoney();
    }

    const matchForm =
        $("matchForm");

    if (matchForm) {

        matchForm.addEventListener(
            "submit",
            submitMatch
        );
    }
}

/* =====================================================
   RUN APPLICATION
===================================================== */

document.addEventListener(
    "DOMContentLoaded",
    start
);