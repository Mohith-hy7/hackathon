const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { db } = require("./database");

const PORT = Number(process.env.PORT) || 5000;
const HOST = process.env.HOST || "0.0.0.0";
const MAX_BODY_BYTES = 1_000_000;

class HttpError extends Error {
  constructor(status, message, code = "BAD_REQUEST") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  });

  response.end(JSON.stringify(payload));
}

function sendError(response, error) {
  const status = error instanceof HttpError ? error.status : 500;
  const code = error instanceof HttpError ? error.code : "INTERNAL_ERROR";

  if (status >= 500) {
    console.error(error);
  }

  sendJson(response, status, {
    error: {
      code,
      message: error.message || "Unexpected server error."
    }
  });
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let body = "";
    let complete = false;

    request.on("data", (chunk) => {
      if (complete) return;

      body += chunk;

      if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
        complete = true;
        reject(
          new HttpError(
            413,
            "Request body is too large.",
            "PAYLOAD_TOO_LARGE"
          )
        );
        request.destroy();
      }
    });

    request.on("end", () => {
      if (complete) return;

      complete = true;

      if (!body.trim()) {
        resolve({});
        return;
      }

      try {
        const parsed = JSON.parse(body);

        if (
          !parsed ||
          Array.isArray(parsed) ||
          typeof parsed !== "object"
        ) {
          throw new Error("JSON body must be an object.");
        }

        resolve(parsed);
      } catch (error) {
        reject(
          new HttpError(
            400,
            error.message,
            "INVALID_JSON"
          )
        );
      }
    });

    request.on("error", reject);
  });
}

function requiredText(value, label, maxLength = 120) {
  if (typeof value !== "string") {
    throw new HttpError(
      400,
      `${label} is required.`,
      "VALIDATION_ERROR"
    );
  }

  const text = value.trim();

  if (!text || text.length > maxLength) {
    throw new HttpError(
      400,
      `${label} must be between 1 and ${maxLength} characters.`,
      "VALIDATION_ERROR"
    );
  }

  return text;
}

function optionalText(value, label, maxLength = 500) {
  if (value === undefined || value === null || value === "") {
    return null;
  }

  return requiredText(value, label, maxLength);
}

function numberValue(
  value,
  label,
  { min = 0, max = Number.MAX_SAFE_INTEGER } = {}
) {
  const number =
    typeof value === "number"
      ? value
      : Number(value);

  if (
    !Number.isFinite(number) ||
    number < min ||
    number > max
  ) {
    throw new HttpError(
      400,
      `${label} must be a number between ${min} and ${max}.`,
      "VALIDATION_ERROR"
    );
  }

  return number;
}

function queryNumber(value, label, options) {
  if (value === null || value === "") {
    return null;
  }

  return numberValue(value, label, options);
}

function riskScore(level) {
  return {
    LOW: 25,
    MEDIUM: 55,
    HIGH: 82
  }[level] || 0;
}

function matchRecommendation(score) {
  if (score >= 80) {
    return "Excellent hive location for pollination.";
  }

  if (score >= 60) {
    return "Good location, but monitor flower availability.";
  }

  return "High risk location. Consider another hive location.";
}

function buildMatch(
  crop,
  distanceKm,
  flowerAvailability
) {
  let score = 100;

  if (distanceKm > 5) {
    score -= 35;
  } else if (distanceKm > 3) {
    score -= 20;
  } else if (distanceKm > 2) {
    score -= 10;
  }

  if (flowerAvailability < 50) {
    score -= 30;
  } else if (flowerAvailability < 70) {
    score -= 15;
  }

  score = Math.max(0, score);

  return {
    crop,
    distanceKm,
    flowerAvailability,
    score,
    recommendation: matchRecommendation(score)
  };
}

function dashboard() {
  const hiveAverages = db
    .prepare(
      "SELECT ROUND(AVG(health_score)) AS beeHealth, ROUND(AVG(pollination_score)) AS pollination FROM hives"
    )
    .get();

  const activeAlert = db
    .prepare(
      "SELECT * FROM pesticide_alerts WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    )
    .get();

  const count = (table) =>
    db
      .prepare(`SELECT COUNT(*) AS count FROM ${table}`)
      .get()
      .count;

  const verifiedBatches = db
    .prepare(
      "SELECT COUNT(*) AS count FROM honey_products WHERE quality_status = 'Verified'"
    )
    .get()
    .count;

  return {
    beeHealth: hiveAverages.beeHealth || 0,
    pollination: hiveAverages.pollination || 0,

    pesticideRisk: activeAlert
      ? {
          level: activeAlert.risk_level,
          score: riskScore(activeAlert.risk_level)
        }
      : {
          level: "LOW",
          score: 0
        },

    honeyBatches: verifiedBatches,
    honeyProducts: count("honey_products"),

    pesticideAlerts: db
      .prepare(
        "SELECT COUNT(*) AS count FROM pesticide_alerts WHERE status = 'active'"
      )
      .get()
      .count,

    farmers: count("farmers"),
    beekeepers: count("beekeepers"),

    latestAlert: activeAlert || null
  };
}

function normaliseHoney(body) {
  return {
    seller_name: requiredText(
      body.seller_name ?? body.sellerName,
      "Seller name"
    ),

    honey_type: requiredText(
      body.honey_type ?? body.honeyType,
      "Honey type",
      50
    ),

    price_per_kg: numberValue(
      body.price_per_kg ?? body.pricePerKg,
      "Price per kg",
      {
        min: 0,
        max: 1_000_000
      }
    ),

    quantity_kg: numberValue(
      body.quantity_kg ?? body.quantityKg,
      "Quantity",
      {
        min: 0,
        max: 1_000_000
      }
    ),

    origin: requiredText(
      body.origin,
      "Origin"
    ),

    batch_id: requiredText(
      body.batch_id ?? body.batchId,
      "Batch ID",
      60
    ).toUpperCase(),

    quality_status:
      optionalText(
        body.quality_status ?? body.qualityStatus,
        "Quality status",
        40
      ) || "Pending"
  };
}

async function handleApi(request, response, url) {
  const { pathname, searchParams } = url;
  const method = request.method;

  if (
    method === "GET" &&
    pathname === "/api/health"
  ) {
    return sendJson(response, 200, {
      status: "ok",
      service: "BeeGuard API"
    });
  }

  if (
    method === "GET" &&
    pathname === "/api/dashboard"
  ) {
    return sendJson(
      response,
      200,
      dashboard()
    );
  }

  if (
    method === "GET" &&
    pathname === "/api/honey"
  ) {
    const type = searchParams.get("type");

    const maxPrice = queryNumber(
      searchParams.get("maxPrice"),
      "Maximum price",
      {
        min: 0,
        max: 1_000_000
      }
    );

    const verifiedOnly =
      searchParams.get("verified") === "true";

    const filters = [];
    const values = [];

    if (type) {
      filters.push("honey_type = ?");
      values.push(
        requiredText(
          type,
          "Honey type",
          50
        )
      );
    }

    if (maxPrice !== null) {
      filters.push("price_per_kg <= ?");
      values.push(maxPrice);
    }

    if (verifiedOnly) {
      filters.push(
        "quality_status = 'Verified'"
      );
    }

    const where = filters.length
      ? `WHERE ${filters.join(" AND ")}`
      : "";

    const products = db
      .prepare(
        `SELECT * FROM honey_products
         ${where}
         ORDER BY price_per_kg ASC, id ASC`
      )
      .all(...values);

    return sendJson(
      response,
      200,
      products
    );
  }

  if (
    method === "GET" &&
    pathname === "/api/honey/compare"
  ) {
    const type = requiredText(
      searchParams.get("type") ||
        "Wildflower",
      "Honey type",
      50
    );

    const products = db
      .prepare(
        "SELECT * FROM honey_products WHERE honey_type = ? ORDER BY price_per_kg ASC, id ASC"
      )
      .all(type);

    return sendJson(
      response,
      200,
      products
    );
  }

  if (
    method === "GET" &&
    pathname === "/api/buyer/search"
  ) {
    const type = requiredText(
      searchParams.get("type") ||
        "Wildflower",
      "Honey type",
      50
    );

    const maxPrice =
      queryNumber(
        searchParams.get("maxPrice"),
        "Maximum price",
        {
          min: 0,
          max: 1_000_000
        }
      ) ?? 999999;

    const products = db
      .prepare(
        `SELECT * FROM honey_products
         WHERE honey_type = ? AND price_per_kg <= ?
         ORDER BY price_per_kg ASC, id ASC`
      )
      .all(type, maxPrice);

    return sendJson(response, 200, {
      honeyType: type,
      maximumPrice: maxPrice,
      results: products
    });
  }

  // FIXED HONEY BATCH ROUTE
  const batchMatch = pathname.match(
    /^\/api\/honey\/batch\/([^/]+)$/
  );

  if (
    method === "GET" &&
    batchMatch
  ) {
    const batchId = decodeURIComponent(
      batchMatch[1]
    )
      .trim()
      .toUpperCase();

    const product = db
      .prepare(
        "SELECT * FROM honey_products WHERE batch_id = ? COLLATE NOCASE"
      )
      .get(batchId);

    if (!product) {
      throw new HttpError(
        404,
        "Batch not found.",
        "BATCH_NOT_FOUND"
      );
    }

    return sendJson(
      response,
      200,
      product
    );
  }

  if (
    method === "POST" &&
    pathname === "/api/honey"
  ) {
    const honey = normaliseHoney(
      await readJson(request)
    );

    try {
      const result = db
        .prepare(
          `INSERT INTO honey_products
           (seller_name, honey_type, price_per_kg, quantity_kg, origin, batch_id, quality_status)
           VALUES (?, ?, ?, ?, ?, ?, ?)`
        )
        .run(
          honey.seller_name,
          honey.honey_type,
          honey.price_per_kg,
          honey.quantity_kg,
          honey.origin,
          honey.batch_id,
          honey.quality_status
        );

      const product = db
        .prepare(
          "SELECT * FROM honey_products WHERE id = ?"
        )
        .get(
          result.lastInsertRowid
        );

      return sendJson(
        response,
        201,
        {
          success: true,
          product
        }
      );
    } catch (error) {
      if (
        String(error.message).includes(
          "UNIQUE"
        )
      ) {
        throw new HttpError(
          409,
          "That batch ID already exists.",
          "DUPLICATE_BATCH"
        );
      }

      throw error;
    }
  }

  if (
    method === "GET" &&
    pathname === "/api/alerts"
  ) {
    const status =
      searchParams.get("status");

    if (
      status &&
      !["active", "protected"].includes(
        status
      )
    ) {
      throw new HttpError(
        400,
        "Status must be active or protected.",
        "VALIDATION_ERROR"
      );
    }

    const alerts = status
      ? db
          .prepare(
            "SELECT * FROM pesticide_alerts WHERE status = ? ORDER BY id DESC"
          )
          .all(status)
      : db
          .prepare(
            "SELECT * FROM pesticide_alerts ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, id DESC"
          )
          .all();

    return sendJson(
      response,
      200,
      alerts
    );
  }

  if (
    method === "POST" &&
    pathname === "/api/alerts"
  ) {
    const body = await readJson(
      request
    );

    const riskLevel = requiredText(
      body.risk_level ??
        body.riskLevel,
      "Risk level",
      10
    ).toUpperCase();

    if (
      !["LOW", "MEDIUM", "HIGH"].includes(
        riskLevel
      )
    ) {
      throw new HttpError(
        400,
        "Risk level must be LOW, MEDIUM, or HIGH.",
        "VALIDATION_ERROR"
      );
    }

    const alert = {
      farmName: requiredText(
        body.farm_name ??
          body.farmName,
        "Farm name"
      ),

      distanceKm: numberValue(
        body.distance_km ??
          body.distanceKm,
        "Distance",
        {
          min: 0,
          max: 1_000
        }
      ),

      riskLevel,

      sprayDate: requiredText(
        body.spray_date ??
          body.sprayDate,
        "Spray date",
        20
      ),

      message: requiredText(
        body.message,
        "Message",
        500
      )
    };

    const result = db
      .prepare(
        `INSERT INTO pesticide_alerts
         (farm_name, distance_km, risk_level, spray_date, message)
         VALUES (?, ?, ?, ?, ?)`
      )
      .run(
        alert.farmName,
        alert.distanceKm,
        alert.riskLevel,
        alert.sprayDate,
        alert.message
      );

    const created = db
      .prepare(
        "SELECT * FROM pesticide_alerts WHERE id = ?"
      )
      .get(
        result.lastInsertRowid
      );

    return sendJson(
      response,
      201,
      {
        success: true,
        alert: created
      }
    );
  }

  // FIXED ALERT PROTECTION ROUTE
  const protectionMatch =
    pathname.match(
      /^\/api\/alerts\/(\d+)\/protect$/
    );

  if (
    method === "POST" &&
    protectionMatch
  ) {
    const alertId = Number(
      protectionMatch[1]
    );

    const alert = db
      .prepare(
        "SELECT * FROM pesticide_alerts WHERE id = ?"
      )
      .get(alertId);

    if (!alert) {
      throw new HttpError(
        404,
        "Pesticide alert not found.",
        "ALERT_NOT_FOUND"
      );
    }

    db.prepare(
      "UPDATE pesticide_alerts SET status = 'protected', protected_at = CURRENT_TIMESTAMP WHERE id = ?"
    ).run(alertId);

    const updated = db
      .prepare(
        "SELECT * FROM pesticide_alerts WHERE id = ?"
      )
      .get(alertId);

    return sendJson(
      response,
      200,
      {
        success: true,
        message:
          "Hive protection was recorded for this pesticide alert.",
        alert: updated
      }
    );
  }

  if (
    method === "POST" &&
    pathname === "/api/matches"
  ) {
    const body = await readJson(
      request
    );

    const match = buildMatch(
      requiredText(
        body.crop,
        "Crop",
        50
      ),

      numberValue(
        body.distanceKm ??
          body.distance_km,
        "Distance",
        {
          min: 0,
          max: 1_000
        }
      ),

      Math.round(
        numberValue(
          body.flowerAvailability ??
            body.flower_availability,
          "Flower availability",
          {
            min: 0,
            max: 100
          }
        )
      )
    );

    const result = db
      .prepare(
        `INSERT INTO hive_matches
         (crop, distance_km, flower_availability, score, recommendation)
         VALUES (?, ?, ?, ?, ?)`
      )
      .run(
        match.crop,
        match.distanceKm,
        match.flowerAvailability,
        match.score,
        match.recommendation
      );

    const savedMatch = db
      .prepare(
        "SELECT * FROM hive_matches WHERE id = ?"
      )
      .get(
        result.lastInsertRowid
      );

    return sendJson(
      response,
      201,
      {
        match: savedMatch
      }
    );
  }

  if (
    method === "GET" &&
    pathname === "/api/matches"
  ) {
    const matches = db
      .prepare(
        "SELECT * FROM hive_matches ORDER BY id DESC LIMIT 20"
      )
      .all();

    return sendJson(
      response,
      200,
      matches
    );
  }

  throw new HttpError(
    404,
    "API route not found.",
    "NOT_FOUND"
  );
}

const staticFiles = new Map([
  [
    "/",
    {
      filename: "index.html",
      type: "text/html; charset=utf-8"
    }
  ],

  [
    "/index.html",
    {
      filename: "index.html",
      type: "text/html; charset=utf-8"
    }
  ],

  [
    "/style.css",
    {
      filename: "style.css",
      type: "text/css; charset=utf-8"
    }
  ],

  [
    "/app.js",
    {
      filename: "app.js",
      type: "application/javascript; charset=utf-8"
    }
  ]
]);

function serveStatic(response, pathname) {
  const asset =
    staticFiles.get(pathname);

  if (!asset) {
    response.writeHead(404, {
      "Content-Type":
        "text/plain; charset=utf-8"
    });

    response.end("Not found");
    return;
  }

  fs.readFile(
    path.join(
      __dirname,
      "public",
      asset.filename
    ),
    (error, file) => {
      if (error) {
        sendError(
          response,
          error
        );
        return;
      }

      response.writeHead(200, {
        "Content-Type": asset.type,
        "Cache-Control": "no-cache"
      });

      response.end(file);
    }
  );
}

const server = http.createServer(
  async (request, response) => {
    const url = new URL(
      request.url,
      `http://${request.headers.host || "localhost"}`
    );

    if (request.method === "OPTIONS") {
      response.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods":
          "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers":
          "Content-Type"
      });

      response.end();
      return;
    }

    try {
      if (
        url.pathname.startsWith("/api/")
      ) {
        await handleApi(
          request,
          response,
          url
        );
      } else {
        serveStatic(
          response,
          url.pathname
        );
      }
    } catch (error) {
      sendError(
        response,
        error
      );
    }
  }
);

server.listen(
  PORT,
  HOST,
  () => {
    console.log(
      `🐝 BeeGuard is running at http://${HOST}:${PORT}`
    );
  }
);

module.exports = { server };