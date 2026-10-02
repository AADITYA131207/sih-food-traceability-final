from flask import Flask, render_template, jsonify, request
from datetime import datetime
import hashlib
import json
import random


app = Flask(__name__)


# ============================================================
# AGRITRACE-IoT
# Offline-First Farm-to-Fork Traceability Prototype
# ============================================================


BATCH = {
    "id": "MANGO-M001",
    "product": "Mango",
    "quantity": "100 kg",
    "origin": "Farm F01"
}


STAGES_TEMPLATE = [
    {
        "name": "FARM",
        "icon": "🌱",
        "location": "Farm F01"
    },
    {
        "name": "TRANSPORT",
        "icon": "🚚",
        "location": "Cold-chain Transport"
    },
    {
        "name": "COLD STORAGE",
        "icon": "❄️",
        "location": "Storage Facility S01"
    },
    {
        "name": "PROCESSING",
        "icon": "🏭",
        "location": "Processing Unit P01"
    },
    {
        "name": "RETAIL",
        "icon": "🏪",
        "location": "Retail Outlet R01"
    }
]


# ============================================================
# RUNTIME STATE
# ============================================================

readings = []
ledger = []

current_stage = 0
last_sync_time = None
last_recovery = None

demo_previous_hash = "GENESIS"


stages = [
    {
        **stage,
        "time": None
    }
    for stage in STAGES_TEMPLATE
]


stages[0]["time"] = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)


# ============================================================
# UTILITIES
# ============================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# ESP32 EDGE HASH
#
# Must match Wokwi:
#
# record_id|batch_id|device_id|timestamp|
# temperature|humidity|gas_raw|previous_hash
# ============================================================

def canonical_edge_string(record):

    return (
        f'{int(record["record_id"])}|'
        f'{record["batch_id"]}|'
        f'{record["device_id"]}|'
        f'{record["timestamp"]}|'
        f'{float(record["temperature"]):.2f}|'
        f'{float(record["humidity"]):.2f}|'
        f'{int(record["gas_raw"])}|'
        f'{record["previous_hash"]}'
    )


def calculate_edge_hash(record):

    raw = canonical_edge_string(record)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# ============================================================
# DASHBOARD DEMO HASH
#
# Demo records are intentionally NOT presented as
# ESP32-verified records.
# ============================================================

def calculate_demo_hash(record):

    payload = {
        "record_id": record["record_id"],
        "batch_id": record["batch_id"],
        "device_id": record["device_id"],
        "timestamp": record["timestamp"],
        "temperature": record["temperature"],
        "humidity": record["humidity"],
        "gas_raw": record["gas_raw"],
        "previous_hash": record["previous_hash"]
    }

    encoded = json.dumps(
        payload,
        sort_keys=True
    ).encode()

    return hashlib.sha256(
        encoded
    ).hexdigest()


# ============================================================
# TRACEABILITY LEDGER HASH
# ============================================================

def calculate_block_hash(block):

    payload = {
        "index": block["index"],
        "timestamp": block["timestamp"],
        "transactions": block["transactions"],
        "previous_hash": block["previous_hash"]
    }

    encoded = json.dumps(
        payload,
        sort_keys=True
    ).encode()

    return hashlib.sha256(
        encoded
    ).hexdigest()


# ============================================================
# GENESIS BLOCK
# ============================================================

def create_genesis_block():

    block = {
        "index": 0,
        "timestamp": now(),

        "transactions": [
            {
                "batch_id": "SYSTEM",
                "event": "GENESIS"
            }
        ],

        "previous_hash": "0"
    }

    block["hash"] = calculate_block_hash(
        block
    )

    ledger.append(block)


create_genesis_block()


# ============================================================
# ADD TRACEABILITY BLOCK
# ============================================================

def add_block(transaction):

    previous_block = ledger[-1]

    block = {
        "index": len(ledger),

        "timestamp": now(),

        "transactions": [
            transaction
        ],

        "previous_hash":
            previous_block["hash"]
    }

    block["hash"] = calculate_block_hash(
        block
    )

    ledger.append(block)

    return block


# ============================================================
# GET REAL ESP32 RECORDS
# ============================================================

def get_edge_records():

    return [
        record
        for record in readings
        if record.get("source") == "WOKWI_ESP32"
    ]


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "AgriTrace-IoT",
        "time": now()
    })


# ============================================================
# DASHBOARD DEMO READING
# ============================================================

@app.route(
    "/generate",
    methods=["POST"]
)
def generate():

    global demo_previous_hash
    global last_sync_time

    existing_ids = [
        record.get("record_id", 0) or 0
        for record in readings
    ]

    record_id = (
        max(existing_ids, default=0) + 1
    )

    record = {

        "record_id": record_id,

        "batch_id": BATCH["id"],

        "device_id": "DEMO-NODE",

        "timestamp": now(),

        "temperature": round(
            random.uniform(
                22.0,
                29.0
            ),
            2
        ),

        "humidity": round(
            random.uniform(
                58.0,
                82.0
            ),
            2
        ),

        "gas_raw": random.randint(
            900,
            2800
        ),

        "previous_hash":
            demo_previous_hash,

        "status": "SYNCED",

        "source": "DASHBOARD_DEMO",

        "edge_verified": False,

        "chain_link_verified": False,

        "integrity": "DEMO"
    }

    record["hash"] = (
        calculate_demo_hash(record)
    )

    demo_previous_hash = (
        record["hash"]
    )

    readings.append(record)

    add_block({

        "batch_id":
            BATCH["id"],

        "event":
            "DEMO_SENSOR_DATA",

        "record_id":
            record["record_id"],

        "device_id":
            record["device_id"],

        "timestamp":
            record["timestamp"],

        "temperature":
            record["temperature"],

        "humidity":
            record["humidity"],

        "gas_raw":
            record["gas_raw"],

        "data_hash":
            record["hash"],

        "source":
            record["source"]
    })

    last_sync_time = now()

    return jsonify({
        "success": True,
        "reading": record
    })


# ============================================================
# REAL WOKWI ESP32 API
# ============================================================

@app.route(
    "/api/sensor",
    methods=["POST"]
)
def receive_sensor():

    global last_sync_time
    global last_recovery

    data = request.get_json(
        silent=True
    ) or {}

    required_fields = [
        "record_id",
        "batch_id",
        "device_id",
        "timestamp",
        "temperature",
        "humidity",
        "gas_raw",
        "previous_hash",
        "hash"
    ]

    missing = [
        field
        for field in required_fields
        if field not in data
    ]

    if missing:

        return jsonify({
            "success": False,
            "message":
                "Missing required fields",
            "missing": missing
        }), 400


    # --------------------------------------------------------
    # NORMALIZE TYPES
    # --------------------------------------------------------

    try:

        record = {

            "record_id":
                int(data["record_id"]),

            "batch_id":
                str(data["batch_id"]),

            "device_id":
                str(data["device_id"]),

            # Keep exact ESP32 timestamp.
            "timestamp":
                data["timestamp"],

            "temperature":
                round(
                    float(
                        data["temperature"]
                    ),
                    2
                ),

            "humidity":
                round(
                    float(
                        data["humidity"]
                    ),
                    2
                ),

            "gas_raw":
                int(data["gas_raw"]),

            "previous_hash":
                str(
                    data["previous_hash"]
                ),

            "hash":
                str(
                    data["hash"]
                ).lower(),

            "status":
                "SYNCED",

            "source":
                "WOKWI_ESP32",

            "server_received_at":
                now()
        }

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "success": False,
            "message":
                "Invalid sensor field type"
        }), 400


    # --------------------------------------------------------
    # BATCH CHECK
    # --------------------------------------------------------

    if (
        record["batch_id"]
        != BATCH["id"]
    ):

        return jsonify({
            "success": False,
            "message":
                "Unknown batch ID"
        }), 400


    # --------------------------------------------------------
    # DUPLICATE CHECK
    #
    # Important for retry/recovery synchronization.
    # --------------------------------------------------------

    duplicate = next(

        (

            existing

            for existing
            in readings

            if (

                existing.get("source")
                == "WOKWI_ESP32"

                and

                existing.get("device_id")
                == record["device_id"]

                and

                existing.get("record_id")
                == record["record_id"]

                and

                existing.get("hash")
                == record["hash"]
            )
        ),

        None
    )


    if duplicate:

        return jsonify({
            "success": True,
            "duplicate": True,
            "message":
                "Record already stored; "
                "duplicate ignored"
        }), 200


    # --------------------------------------------------------
    # VERIFY ESP32 SHA-256
    # --------------------------------------------------------

    expected_hash = (
        calculate_edge_hash(
            record
        )
    )

    if (
        expected_hash
        != record["hash"]
    ):

        return jsonify({

            "success": False,

            "message":
                "Edge SHA-256 verification failed",

            "expected_hash":
                expected_hash,

            "received_hash":
                record["hash"]

        }), 422


    # --------------------------------------------------------
    # VERIFY HASH CHAIN LINK
    # --------------------------------------------------------

    prior_records = [

        existing

        for existing
        in get_edge_records()

        if (
            existing.get("device_id")
            == record["device_id"]
        )
    ]


    if prior_records:

        expected_previous_hash = (
            prior_records[-1]["hash"]
        )

    else:

        expected_previous_hash = (
            "GENESIS"
        )


    if (
        record["previous_hash"]
        != expected_previous_hash
    ):

        return jsonify({

            "success": False,

            "message":
                "Edge hash-chain continuity failed",

            "expected_previous_hash":
                expected_previous_hash,

            "received_previous_hash":
                record["previous_hash"]

        }), 409


    # --------------------------------------------------------
    # VERIFIED EDGE RECORD
    # --------------------------------------------------------

    record["edge_verified"] = True

    record["chain_link_verified"] = True

    record["integrity"] = "VERIFIED"

    readings.append(record)


    # --------------------------------------------------------
    # ADD VERIFIED RECORD TO TRACEABILITY LEDGER
    # --------------------------------------------------------

    block = add_block({

        "batch_id":
            record["batch_id"],

        "event":
            "SENSOR_DATA",

        "record_id":
            record["record_id"],

        "device_id":
            record["device_id"],

        "timestamp":
            record["timestamp"],

        "temperature":
            record["temperature"],

        "humidity":
            record["humidity"],

        "gas_raw":
            record["gas_raw"],

        "edge_hash":
            record["hash"],

        "edge_previous_hash":
            record["previous_hash"],

        "edge_verified":
            True,

        "source":
            record["source"]
    })


    last_sync_time = now()


    # --------------------------------------------------------
    # RECOVERY HINT
    # --------------------------------------------------------

    if prior_records:

        previous_record_id = (
            prior_records[-1][
                "record_id"
            ]
        )

        if (
            record["record_id"]
            >
            previous_record_id + 1
        ):

            last_recovery = {
                "time": now(),
                "message":
                    "Recovery synchronization received"
            }


    return jsonify({

        "success": True,

        "duplicate": False,

        "edge_verified": True,

        "chain_link_verified": True,

        "ledger_block":
            block["index"],

        "message":
            "Edge record verified and stored"

    }), 201


# ============================================================
# VERIFY REAL ESP32 RECORD CHAIN
# ============================================================

@app.route(
    "/verify",
    methods=["GET", "POST"]
)
@app.route(
    "/verify_integrity",
    methods=["GET", "POST"]
)
def verify_edge():

    records = get_edge_records()

    if not records:

        return jsonify({

            "verified": True,

            "status":
                "NO_EDGE_RECORDS",

            "records_verified":
                0,

            "message":
                "No ESP32 edge records received yet."
        })


    previous_hash = "GENESIS"


    for index, record in enumerate(
        records
    ):

        expected_hash = (
            calculate_edge_hash(
                record
            )
        )

        if (
            expected_hash
            != record.get("hash")
        ):

            return jsonify({

                "verified": False,

                "status":
                    "HASH_FAILURE",

                "records_verified":
                    index,

                "message":
                    "Hash mismatch at "
                    f'record #{record["record_id"]}'
            })


        if (
            record.get("previous_hash")
            != previous_hash
        ):

            return jsonify({

                "verified": False,

                "status":
                    "CHAIN_FAILURE",

                "records_verified":
                    index,

                "message":
                    "Chain link mismatch at "
                    f'record #{record["record_id"]}'
            })


        previous_hash = (
            record["hash"]
        )


    return jsonify({

        "verified": True,

        "status":
            "VERIFIED",

        "records_verified":
            len(records),

        "algorithm":
            "SHA-256",

        "message":
            f"All {len(records)} ESP32 edge "
            "records cryptographically verified."
    })


# ============================================================
# VERIFY HASH-LINKED TRACEABILITY LEDGER
# ============================================================

@app.route(
    "/verify-blockchain",
    methods=["GET", "POST"]
)
def verify_ledger():

    for index, block in enumerate(
        ledger
    ):

        expected_hash = (
            calculate_block_hash(
                block
            )
        )

        if (
            expected_hash
            != block.get("hash")
        ):

            return jsonify({

                "verified": False,

                "status":
                    "BLOCK_HASH_FAILURE",

                "message":
                    "Ledger block "
                    f'#{block["index"]} '
                    "has been altered."
            })


        if index > 0:

            previous_block = (
                ledger[index - 1]
            )

            if (
                block["previous_hash"]
                !=
                previous_block["hash"]
            ):

                return jsonify({

                    "verified": False,

                    "status":
                        "CHAIN_LINK_FAILURE",

                    "message":
                        "Ledger chain link broken at "
                        f'block #{block["index"]}.'
                })


    return jsonify({

        "verified": True,

        "status":
            "VERIFIED",

        "blocks_verified":
            len(ledger),

        "message":
            "Hash-linked traceability ledger "
            f"verified: {len(ledger)} "
            "blocks intact."
    })


# ============================================================
# ADVANCE SUPPLY-CHAIN JOURNEY
# ============================================================

@app.route(
    "/next-stage",
    methods=["POST"]
)
def next_stage():

    global current_stage


    if (
        current_stage
        >= len(stages) - 1
    ):

        return jsonify({

            "success": False,

            "message":
                "Batch has reached retail.",

            "current_stage":
                current_stage
        })


    current_stage += 1

    stages[
        current_stage
    ]["time"] = now()


    add_block({

        "batch_id":
            BATCH["id"],

        "event":
            "SUPPLY_CHAIN_STAGE",

        "stage":
            stages[
                current_stage
            ]["name"],

        "location":
            stages[
                current_stage
            ]["location"],

        "timestamp":
            stages[
                current_stage
            ]["time"]
    })


    return jsonify({

        "success": True,

        "stage":
            stages[
                current_stage
            ],

        "current_stage":
            current_stage
    })


# ============================================================
# COMPLETE DEMO RESET
#
# IMPORTANT:
# This is intentionally a prototype/demo reset.
#
# It resets:
# - ESP32 readings
# - edge hash-chain expectation
# - dashboard demo state
# - traceability ledger
# - supply-chain journey
# - synchronization state
#
# After reset, the backend expects:
#
# record_id = 1
# previous_hash = GENESIS
# ============================================================

@app.route(
    "/reset-batch",
    methods=["POST"]
)
def reset_batch():

    global current_stage
    global last_sync_time
    global last_recovery
    global demo_previous_hash
    global readings
    global ledger


    # --------------------------------------------------------
    # CLEAR SENSOR DATA
    # --------------------------------------------------------

    readings.clear()


    # --------------------------------------------------------
    # RESET EDGE / DEMO STATE
    # --------------------------------------------------------

    demo_previous_hash = "GENESIS"

    last_sync_time = None

    last_recovery = None


    # --------------------------------------------------------
    # RESET TRACEABILITY LEDGER
    # --------------------------------------------------------

    ledger.clear()

    create_genesis_block()


    # --------------------------------------------------------
    # RESET SUPPLY-CHAIN JOURNEY
    # --------------------------------------------------------

    current_stage = 0

    for stage in stages:

        stage["time"] = None


    stages[0]["time"] = now()


    # --------------------------------------------------------
    # ADD INITIAL FARM EVENT
    # --------------------------------------------------------

    add_block({

        "batch_id":
            BATCH["id"],

        "event":
            "SUPPLY_CHAIN_STAGE",

        "stage":
            stages[0]["name"],

        "location":
            stages[0]["location"],

        "timestamp":
            stages[0]["time"]
    })


    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return jsonify({

        "success": True,

        "message":
            "Complete demo reset. ESP32 chain ready for GENESIS.",

        "current_stage":
            current_stage,

        "edge_records":
            0,

        "expected_previous_hash":
            "GENESIS",

        "ledger_blocks":
            len(ledger)

    })


# ============================================================
# QR / PROVENANCE PAGE
# ============================================================

@app.route(
    "/trace/<batch_id>"
)
def trace(batch_id):

    if (
        batch_id
        != BATCH["id"]
    ):

        return (
            "Batch not found",
            404
        )


    return render_template(
        "trace.html"
    )


# ============================================================
# DASHBOARD DATA
# ============================================================

@app.route("/data")
def data():

    edge_records = (
        get_edge_records()
    )


    latest = (
        readings[-1]
        if readings
        else None
    )


    latest_edge = (
        edge_records[-1]
        if edge_records
        else None
    )


    if latest_edge:

        edge_state = {

            "state":
                "CONNECTED",

            "message":
                "ESP32 telemetry received"
        }

    else:

        edge_state = {

            "state":
                "WAITING",

            "message":
                "Waiting for ESP32 telemetry"
        }


    return jsonify({

        "batch":
            BATCH,

        "device_id":
            (
                latest_edge.get(
                    "device_id",
                    "NODE-001"
                )

                if latest_edge

                else "NODE-001"
            ),

        "readings":
            readings,

        "edge_readings":
            edge_records,

        "latest":
            latest,

        "latest_edge":
            latest_edge,

        "synced":
            len(edge_records),

        # Actual pending count exists on ESP32 MicroSD.
        # Backend must not invent it.
        "buffered":
            0,

        "last_sync_time":
            last_sync_time,

        "last_recovery":
            last_recovery,

        "ledger":
            ledger,

        # Compatibility name
        "blockchain":
            ledger,

        "stages":
            stages,

        "current_stage":
            current_stage,

        "edge_state":
            edge_state,

        "prototype": {

            "transport":
                "HTTPS/JSON prototype",

            "integrity":
                "SHA-256",

            "storage":
                "MicroSD at edge",

            "gas_sensor":
                "Gas/VOC pipeline validation",

            "mqtt":
                "Finale architecture",

            "ethylene":
                "Dedicated sensor planned",

            "energy_harvesting":
                "Finale / field deployment"
        }
    })


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
