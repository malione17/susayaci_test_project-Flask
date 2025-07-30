import os
import sqlite3


DB_PATH = "sensor.db.backup"

def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT,
                cam_device_id TEXT,
                probe_id INTEGER,
                manual_value INTEGER,
                remote_value INTEGER,
                timestamp TEXT,
                fcnt INTEGER,
                raw_data TEXT,
                image_path TEXT
            )
        """)
        c.execute("""
            CREATE TABLE device_info (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deveui TEXT UNIQUE,
                cam_device_id TEXT,
                probe_count INTEGER
            )
        """)
        conn.commit()
        conn.close()


def get_sensor_data():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM sensor_data")
    rows = c.fetchall()
    conn.close()
    return rows
def get_db():
    return sqlite3.connect(DB_PATH)

def create_device_info(deveui, cam_device_id, probe_count):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO device_info (deveui, cam_device_id, probe_count)
            VALUES (?, ?, ?)
        """, (deveui, cam_device_id, probe_count))
        conn.commit()
    except sqlite3.IntegrityError as e:
        print(f"IntegrityError: {e}")
    finally:
        conn.close()

def get_device_info_by_deveui(deveui):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM device_info WHERE deveui = ?", (deveui,))
    result = c.fetchone()
    conn.close()
    return result
def get_device_info_by_cam_device_id(cam_device_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM device_info WHERE cam_device_id = ?", (cam_device_id,))
    result = c.fetchone()
    conn.close()
    return result

def update_device_info(deveui, cam_device_id=None, probe_count=None):
    conn = get_db()
    c = conn.cursor()
    fields = []
    values = []

    if cam_device_id is not None:
        fields.append("cam_device_id = ?")
        values.append(cam_device_id)
    if probe_count is not None:
        fields.append("probe_count = ?")
        values.append(probe_count)

    if fields:
        values.append(deveui)
        query = f"UPDATE device_info SET {', '.join(fields)} WHERE deveui = ?"
        c.execute(query, tuple(values))
        conn.commit()

    conn.close()

def delete_device_info(deveui):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM device_info WHERE deveui = ?", (deveui,))
    conn.commit()
    conn.close()

def get_all_devices():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM device_info")
    rows = c.fetchall()
    conn.close()
    return rows