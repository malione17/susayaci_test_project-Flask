from flask import request, render_template, send_from_directory, Blueprint, current_app, url_for, redirect
from .db import get_db, get_device_info_by_cam_device_id
import os, base64, datetime
from .websocket_handler import notify_clients
import os
from app.mqtt_handler import pending_photos

# 1) __file__ bu dosyanın bulunduğu klasörü (app/) gösterir
HERE = os.path.dirname(__file__)

# 2) oradan bir üst klasöre çıkarak proje kökünü bul
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, '..'))

# 3) static/images alt klasörünü oluştur
IMAGES_DIR = os.path.join(PROJECT_ROOT, 'static', 'images')

# (isteğe bağlı) doğrulamak için yazdır
print("IMAGES_DIR:", IMAGES_DIR)



# Bu ayarlar, mqtt_handler.py dosyasındakiyle aynı olmalıdır.
MQTT_BROKER = "MQTT server IP"
MQTT_PORT_FOR_ROUTES = 1883


bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route("/last_data")
def last_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sensor_data ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()

    data = []
    for row in rows:
        record = dict(zip(["id", "device_id", "cam_device_id", "probe_id", "manual_value", "remote_value", "timestamp", "fcnt", "raw_data", "image_path"], row))

        if record["image_path"]:
            record["image_path"] = f"/static/images/{record['image_path']}"

        data.append(record)

    return {"data": data}, 200


@bp.route("/upload", methods=["POST", "PUT"])
def upload_image():


    content_type = request.headers.get("Content-Type", "")
    cam_device_id = request.headers.get("X-Device-ID", "")
    if not cam_device_id:
        return {"status": "error", "message": "X-Device-ID header eksik"}, 400
    record_id = pending_photos.get(cam_device_id)
    if not record_id:
        print("[UPLOAD] pending_photos'ta eşleşme bulunamadı:", pending_photos)
        return {"status": "error", "message": "Cihaz ID'si bulunamadı"}, 400

    # Kamera cihaz bilgisi
    row = get_device_info_by_cam_device_id(cam_device_id)
    if not row:
        return {"status": "error", "message": "Cihaz bulunamadı"}, 400
    device_id = row[1]
    probe_id = row[3]

    # --- 1. JPEG akışı (image/jpeg) ---
    if content_type.startswith("image/"):
        try:
            img_data = request.get_data()

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename  = f"{device_id}_{timestamp}.jpg"
            filepath  = os.path.join(IMAGES_DIR, filename)

            with open(filepath, "wb") as f:
                f.write(img_data)

            # Veritabanı güncelleme → pending_photos kullan
            conn = get_db()
            c = conn.cursor()
            record_id = pending_photos.get(cam_device_id)
            if record_id:
                c.execute("UPDATE sensor_data SET image_path = ? WHERE id = ?", (filename, record_id))
                conn.commit()
                del pending_photos[cam_device_id]
            else:
                print(f"[UPLOAD] pending_photos'ta eşleşme bulunamadı: {cam_device_id}")
                record_id = None
            conn.close()

            # WebSocket bildirimi
            notify_clients({
                "id":           record_id,
                "timestamp":    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "device_id":    device_id,
                "probe_id":     probe_id,
                "manual_value": "-",
                "remote_value": "-",
                "image_url":    f"/images/{filename}"
            })

            return {"status": "success", "image_path": filename}, 200

        except Exception as e:
            return {"status": "error", "message": str(e)}, 500

    # --- 2. JSON Base64 akışı ---
    try:
        data = request.get_json(force=True)
        device_id = data.get("deveui")
        probe_id  = int(data.get("probe_id", 0))
        image_b64 = data.get("content", "")

        if not device_id or probe_id <= 0 or not image_b64:
            return {"status": "error", "message": "Eksik veya hatalı parametre"}, 400

        clean_b64   = "".join(image_b64.split())
        clean_bytes = clean_b64.encode("ascii", errors="ignore")
        img_data    = base64.b64decode(clean_bytes)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"{device_id}_{timestamp}.jpg"
        filepath  = os.path.join(IMAGES_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)

        # Veritabanı güncelleme (en son kayıt)
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id FROM sensor_data WHERE cam_device_id = ? AND probe_id = ? ORDER BY id DESC LIMIT 1",
            (device_id, probe_id)
        )
        row = c.fetchone()
        if row:
            c.execute("UPDATE sensor_data SET image_path = ? WHERE id = ?", (filename, row[0]))
            conn.commit()
        conn.close()

        notify_clients({
            "id":           row[0] if row else None,
            "timestamp":    datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "device_id":    device_id,
            "probe_id":     probe_id,
            "manual_value": "-",
            "remote_value": "-",
            "image_url":    f"/images/{filename}"
        })

        return {"status": "success", "image_path": filename}, 200

    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@bp.route("/set_manual_value", methods=["POST"])
def set_manual_value():
    try:
        data = request.get_json()

        manual_raw = data.get("manual_value")
        record_id = data.get("record_id")

        if manual_raw is None or not str(manual_raw).isdigit() or int(manual_raw) < 0:
            return {"status": "error", "message": "Geçersiz manuel değer!"}, 400

        if record_id is None or not str(record_id).isdigit() or int(record_id) < 1:
            return {"status": "error", "message": "Geçersiz kayıt ID!"}, 400

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            UPDATE sensor_data 
            SET manual_value = ? 
            WHERE id = ?
        """, (int(manual_raw), int(record_id)))
        conn.commit()
        updated = c.rowcount
        conn.close()

        if updated == 0:
            return {"status": "error", "message": "Kayıt bulunamadı!"}, 404

        return {"status": "success"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@bp.route("/gallery")
def gallery():

    conn = get_db()
    c = conn.cursor()
    # image_path'i olan tüm sensor_data kayıtlarını çek
    # En yeni fotoğrafları en başta göstermek için id'ye göre tersten sırala
    c.execute("SELECT id, image_path, manual_value,cam_device_id FROM sensor_data WHERE image_path IS NOT NULL ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    images = []
    for row in rows:
        record_id = row[0]
        image_path_db = row[1] # Veritabanındaki /static/images/filename.jpg yolu
        manual_value = row[2]
        cam_device_id = row[3]

        # Sadece dosya adını al (örneğin: esp32cam_20250707_100951.jpg)
        filename = os.path.basename(image_path_db)

        images.append({
            "id": record_id,        # Veritabanındaki kayıt ID'si
            "filename": filename,   # Dosya adı
            "url": image_path_db,   # Tam URL (Flask bunu servis edecek)
            "manual_value": manual_value, # Kayıtlı manuel değer
            "cam_device_id": cam_device_id
        })

    return render_template("gallery.html", images=images)



@bp.route("/images/<path:filename>")
def get_image(filename):
    """ESP32-CAM ve diğer kaynaklardan gelen fotoğrafları servis eder"""
    try:
        # Dosyanın var olup olmadığını kontrol et
        filepath = os.path.join(IMAGES_DIR, filename)
        if not os.path.exists(filepath):
            return {"error": "Fotoğraf bulunamadı"}, 404

        return send_from_directory(IMAGES_DIR, filename)
    except Exception as e:
        return {"error": str(e)}, 500

@bp.route("/static/images/<path:filename>")
def get_static_image(filename):
    """Eski static/images yolunu da destekle"""
    try:
        # Önce images/ klasöründe ara
        filepath = os.path.join(IMAGES_DIR, filename)
        if os.path.exists(filepath):
            return send_from_directory(IMAGES_DIR, filename)

        # Eski static/images klasöründe ara
        base_dir = os.path.dirname(os.path.abspath(__file__))
        static_images_dir = os.path.join(base_dir, 'static', 'images')
        static_filepath = os.path.join(static_images_dir, filename)
        if os.path.exists(static_filepath):
            return send_from_directory(static_images_dir, filename)

        return {"error": "Fotoğraf bulunamadı"}, 404
    except Exception as e:
        return {"error": str(e)}, 500

@bp.route("/devices")
def list_devices():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM device_info")
    rows = c.fetchall()
    conn.close()

    # Veritabanı verilerini daha kullanışlı formata dönüştür
    devices = []
    for row in rows:
        devices.append({
            "id": row[0],
            "deveui": row[1],
            "cam_device_id": row[2],
            "probe_count": row[3]
        })

    return render_template("devices.html", devices=devices)

@bp.route("/devices/add", methods=["POST"])
def add_device():
    try:
        # Form verisi veya JSON verisi olabilir
        if request.is_json:
            data = request.json
        else:
            data = request.form

        deveui = data.get("deveui", "").strip()
        cam_device_id = data.get("cam_device_id", "").strip()
        probe_count = int(data.get("probe_count", 1))

        # Validasyon
        if not deveui:
            return {"status": "error", "message": "DevEUI zorunludur"}, 400
        if not cam_device_id:
            return {"status": "error", "message": "Cam Device ID zorunludur"}, 400
        if probe_count < 1:
            return {"status": "error", "message": "Probe sayısı 1'den az olamaz"}, 400

        conn = get_db()
        c = conn.cursor()

        # Duplicate kontrolü
        c.execute("SELECT id FROM device_info WHERE deveui = ?", (deveui,))
        if c.fetchone():
            conn.close()
            return {"status": "error", "message": "Bu DevEUI zaten kayıtlı"}, 400

        c.execute("""
            INSERT INTO device_info (deveui, cam_device_id, probe_count)
            VALUES (?, ?, ?)
        """, (deveui, cam_device_id, probe_count))
        conn.commit()
        conn.close()

        return {"status": "success", "message": "Cihaz başarıyla eklendi"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@bp.route("/devices/<int:device_id>", methods=["GET"])
def get_device(device_id):
    """Tek bir cihazın detaylarını getir"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM device_info WHERE id = ?", (device_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return {"status": "error", "message": "Cihaz bulunamadı"}, 404

        device = {
            "id": row[0],
            "deveui": row[1],
            "cam_device_id": row[2],
            "probe_count": row[3]
        }

        return {"status": "success", "device": device}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@bp.route("/devices/<int:device_id>", methods=["PUT"])
def update_device(device_id):
    """Cihaz bilgilerini güncelle"""
    try:
        data = request.json
        deveui = data.get("deveui", "").strip()
        cam_device_id = data.get("cam_device_id", "").strip()
        probe_count = int(data.get("probe_count", 1))

        # Validasyon
        if not deveui:
            return {"status": "error", "message": "DevEUI zorunludur"}, 400
        if not cam_device_id:
            return {"status": "error", "message": "Cam Device ID zorunludur"}, 400
        if probe_count < 1:
            return {"status": "error", "message": "Probe sayısı 1'den az olamaz"}, 400

        conn = get_db()
        c = conn.cursor()

        # Cihazın var olduğunu kontrol et
        c.execute("SELECT id FROM device_info WHERE id = ?", (device_id,))
        if not c.fetchone():
            conn.close()
            return {"status": "error", "message": "Cihaz bulunamadı"}, 404

        # Duplicate kontrolü (kendi ID'si hariç)
        c.execute("SELECT id FROM device_info WHERE deveui = ? AND id != ?", (deveui, device_id))
        if c.fetchone():
            conn.close()
            return {"status": "error", "message": "Bu DevEUI başka bir cihazda kullanılıyor"}, 400

        c.execute("""
            UPDATE device_info 
            SET deveui = ?, cam_device_id = ?, probe_count = ?
            WHERE id = ?
        """, (deveui, cam_device_id, probe_count, device_id))
        conn.commit()
        conn.close()

        return {"status": "success", "message": "Cihaz başarıyla güncellendi"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@bp.route("/devices/<int:device_id>", methods=["DELETE"])
def delete_device(device_id):
    """Cihazı sil"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Cihazın var olduğunu kontrol et
        c.execute("SELECT deveui FROM device_info WHERE id = ?", (device_id,))
        device = c.fetchone()
        if not device:
            conn.close()
            return {"status": "error", "message": "Cihaz bulunamadı"}, 404

        # Cihaza ait sensor verilerini kontrol et
        c.execute("SELECT COUNT(*) FROM sensor_data WHERE device_id = ?", (device[0],))
        data_count = c.fetchone()[0]

        if data_count > 0:
            # Veri varsa silme işlemini onaylatabilirsiniz
            force_delete = request.args.get('force', 'false').lower() == 'true'
            if not force_delete:
                conn.close()
                return {
                    "status": "warning",
                    "message": f"Bu cihaza ait {data_count} adet veri kaydı var. Silmek için force=true parametresi gönderin.",
                    "data_count": data_count
                }, 409
            else:
                # Önce sensor verilerini sil
                c.execute("DELETE FROM sensor_data WHERE device_id = ?", (device[0],))

        # Cihazı sil
        c.execute("DELETE FROM device_info WHERE id = ?", (device_id,))
        conn.commit()
        conn.close()

        return {"status": "success", "message": "Cihaz başarıyla silindi"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@bp.route("/devices/api")
def devices_api():
    """API endpoint - JSON formatında cihaz listesi"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM device_info ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()

        devices = []
        for row in rows:
            devices.append({
                "id": row[0],
                "deveui": row[1],
                "cam_device_id": row[2],
                "probe_count": row[3]
            })

        return {"status": "success", "devices": devices}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

def register_routes(app):
    app.register_blueprint(bp)