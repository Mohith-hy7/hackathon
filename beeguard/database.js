const fs = require("node:fs");
const path = require("node:path");
const { DatabaseSync } = require("node:sqlite");

const dataDirectory = path.join(__dirname, "data");
fs.mkdirSync(dataDirectory, { recursive: true });

const databasePath = process.env.BEEGUARD_DB_PATH || path.join(dataDirectory, "beeguard.db");
fs.mkdirSync(path.dirname(databasePath), { recursive: true });
const db = new DatabaseSync(databasePath);
db.exec("PRAGMA foreign_keys = ON;");

db.exec(`
  CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    farm_name TEXT NOT NULL,
    location TEXT NOT NULL,
    crop TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS beekeepers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    apiary_name TEXT NOT NULL,
    location TEXT NOT NULL,
    hive_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS hives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beekeeper_id INTEGER NOT NULL,
    hive_name TEXT NOT NULL,
    location TEXT NOT NULL,
    health_score INTEGER NOT NULL CHECK (health_score BETWEEN 0 AND 100),
    pollination_score INTEGER NOT NULL CHECK (pollination_score BETWEEN 0 AND 100),
    FOREIGN KEY (beekeeper_id) REFERENCES beekeepers(id)
  );

  CREATE TABLE IF NOT EXISTS honey_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name TEXT NOT NULL,
    honey_type TEXT NOT NULL,
    price_per_kg REAL NOT NULL CHECK (price_per_kg >= 0),
    quantity_kg REAL NOT NULL CHECK (quantity_kg >= 0),
    origin TEXT NOT NULL,
    batch_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
    quality_status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS pesticide_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_name TEXT NOT NULL,
    distance_km REAL NOT NULL CHECK (distance_km >= 0),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    spray_date TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'protected')),
    protected_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS hive_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop TEXT NOT NULL,
    distance_km REAL NOT NULL,
    flower_availability INTEGER NOT NULL,
    score INTEGER NOT NULL,
    recommendation TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  );

  CREATE INDEX IF NOT EXISTS idx_honey_type_price
    ON honey_products (honey_type, price_per_kg);
  CREATE INDEX IF NOT EXISTS idx_alert_status_created
    ON pesticide_alerts (status, created_at DESC);
`);

function rowCount(tableName) {
  return db.prepare(`SELECT COUNT(*) AS count FROM ${tableName}`).get().count;
}

function seedDemoData() {
  if (rowCount("farmers") === 0) {
    const insertFarmer = db.prepare(
      "INSERT INTO farmers (name, farm_name, location, crop) VALUES (?, ?, ?, ?)"
    );
    insertFarmer.run("Ananya Rao", "Green Valley Farm", "Mysuru, Karnataka", "Sunflower");
    insertFarmer.run("Vikram Shah", "Golden Fields", "Mandya, Karnataka", "Mustard");
  }

  if (rowCount("beekeepers") === 0) {
    const insertBeekeeper = db.prepare(
      "INSERT INTO beekeepers (name, apiary_name, location, hive_count) VALUES (?, ?, ?, ?)"
    );
    insertBeekeeper.run("Meera Nair", "Green Valley Apiary", "Mysuru, Karnataka", 14);
    insertBeekeeper.run("Arjun Kumar", "BeeFarm Karnataka", "Mandya, Karnataka", 10);
  }

  if (rowCount("hives") === 0) {
    const beekeepers = db.prepare("SELECT id FROM beekeepers ORDER BY id ASC LIMIT 2").all();
    if (beekeepers.length === 2) {
      const insertHive = db.prepare(
        "INSERT INTO hives (beekeeper_id, hive_name, location, health_score, pollination_score) VALUES (?, ?, ?, ?, ?)"
      );
      insertHive.run(beekeepers[0].id, "Sunrise Hive", "Mysuru, Karnataka", 94, 89);
      insertHive.run(beekeepers[0].id, "Orchard Hive", "Mysuru, Karnataka", 91, 86);
      insertHive.run(beekeepers[1].id, "Mustard Hive", "Mandya, Karnataka", 91, 86);
    }
  }

  if (rowCount("honey_products") === 0) {
    const insertHoney = db.prepare(
      `INSERT INTO honey_products
       (seller_name, honey_type, price_per_kg, quantity_kg, origin, batch_id, quality_status)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    );
    [
      ["Green Valley Apiary", "Wildflower", 420, 100, "Karnataka", "BG2026-001", "Verified"],
      ["BeeFarm Karnataka", "Wildflower", 380, 75, "Karnataka", "BG2026-002", "Verified"],
      ["Honey World", "Wildflower", 450, 120, "Karnataka", "BG2026-003", "Verified"],
      ["Nature Bees", "Mustard", 350, 50, "Mysuru", "BG2026-004", "Verified"],
      ["Pure Hive", "Sunflower", 400, 80, "Mandya", "BG2026-005", "Verified"]
    ].forEach((product) => insertHoney.run(...product));
  }

  if (rowCount("pesticide_alerts") === 0) {
    db.prepare(
      `INSERT INTO pesticide_alerts
       (farm_name, distance_km, risk_level, spray_date, message)
       VALUES (?, ?, ?, ?, ?)`
    ).run(
      "Green Valley Farm",
      1.8,
      "HIGH",
      new Date().toISOString().slice(0, 10),
      "Pesticide spraying detected near bee colonies. Move hives away from the spray zone before treatment begins."
    );
  }
}

seedDemoData();

module.exports = { db };
