import os
import time
import json
import base64
import threading
import requests
import paho.mqtt.client as mqtt
from .db import get_all_devices, get_device_info_by_deveui, get_sensor_data
from .db import get_db
from app.websocket_handler import notify_clients




# --- Sabitler ---
MQTT_BROKER          = "MQTT SERVER IP"
HTTP_SERVER          = "YOUR LOCAL IP"  # cam_device_id -> record_id
pending_photos = {}

# Resimlerin kaydedileceği klasör
ROOT_DIR   = os.path.abspath(os.path.dirname(__file__))
IMAGES_DIR = os.path.join(ROOT_DIR, "static", "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


def on_connect(client, userdata, flags, rc):

    print(f"[MQTT] Bağlandı (rc={rc}), subscribe ediliyor…")
    rows = get_all_devices()  # DB bağlantısını başlat
    for row in rows:
        deveui = row[1]
        cam_device_id = row[2]
        probe_count = row[3]
        print(f"[MQTT] Cihaz: {deveui}, Kamera ID: {cam_device_id}, Probe Sayısı: {probe_count}")
        client.subscribe(f"application/+/device/{deveui}/event/up")
        print(f"[MQTT] Subscribed to: application/+/device/{deveui}/event/up")


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload
    if topic.startswith("esp_cam/") and topic.endswith("/sensor"):
        cam_device_id = topic.split("/")[1]
        handle_esp32cam_image(cam_device_id, payload)
        return  # diğerlerini kontrol etme
    # Pulse mesajı
    if topic.endswith(f"/event/up"):
        parts = topic.split("/")
        deveui = parts[3]  # index 4 corresponds to the deveui

        print("Extracted deveui:", deveui)
        print(f"[MQTT] ❗ Pulse mesajı: {topic} ({len(payload)} bytes)")

        try:
            j = json.loads(payload.decode('utf-8'))
            raw_bytes = base64.b64decode(j["data"])
            raw_hex = raw_bytes.hex()

            pulse = int.from_bytes(raw_bytes[0:4], byteorder='big') # 4 byte
            interval = int.from_bytes(raw_bytes[4:7], byteorder='big')  # 3 byte
            div = int.from_bytes(raw_bytes[7:8], byteorder='big')  # 1 byte
            battery = int.from_bytes(raw_bytes[8:9], byteorder='big')  # 1 byte

            print(f"[MQTT] → Pulse: {pulse}, interval: {interval}, div: {div}, battery:{battery}" )
            print(f"Raw hex   : {raw_hex}")
            print(f"Byte Length: {len(raw_bytes)}")

        except Exception as e:
            print("[MQTT] Pulse parse hatası:", e)
            return


        # Kamera komutunu yayınla
        row = get_device_info_by_deveui(deveui)
        print(f"[MQTT] {row}")
        if not row:
            print(f"[MQTT] Cihaz bilgisi bulunamadı: {deveui}")
            return
        cam_device_id = row[2]

        if pulse > 0 or interval > 0:
            probe_id = 1  # Sabit çünkü tek pulse var
            pulse_value = pulse
            cmd = {
                "command": "take_photo",
                "probe_id": probe_id,
                "timestamp": int(time.time())
            }

            client.publish(f"esp_cam/{cam_device_id}/command", json.dumps(cmd))
            print(f"[MQTT] Kamera komutu gönderildi → esp_cam/{cam_device_id}/command {cmd}")

            # DB’ye kaydet
            try:
                timestamp = j.get("time") or int(time.time())
                fcnt = j.get("fCnt")

                conn = get_db();
                c = conn.cursor()
                c.execute("""
                          INSERT INTO sensor_data
                          (device_id, cam_device_id, probe_id,
                           remote_value, timestamp, fcnt, raw_data)
                          VALUES (?, ?, ?, ?, ?, ?, ?)
                          """, (
                              deveui,
                              cam_device_id,
                              probe_id,
                              pulse_value,
                              timestamp,
                              fcnt,
                              raw_hex
                          ))
                conn.commit()
                record_id = c.lastrowid
                pending_photos[cam_device_id] = record_id
            finally:
                conn.close()

            # WebSocket’e bildir
            notify_clients({
                "id": record_id,
                "fcnt": fcnt,
                "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
                "device_id": deveui,
                "probe_id": probe_id,
                "manual_value": None,
                "remote_value": pulse_value,
                "image_path": None
            })
            print("[MQTT] Dashboard’a pulse gönderildi.")


def handle_esp32cam_image(cam_device_id, fb_buf):
    """ESP32-CAM’den gelen ham JPEG buffer’ını işleyip kaydeder ve WebSocket’e bildirir."""
    if len(fb_buf) < 100:
        print("[MQTT] Fotoğraf verisi çok küçük, iptal ediliyor.")
        return

    ts = int(time.time())
    filename = f"{cam_device_id}_{ts}.jpg"
    filepath = os.path.join(IMAGES_DIR, filename)
    url_path = f"/images/{filename}"

    # Dosyaya yaz
    try:
        with open(filepath, "wb") as f:
            f.write(fb_buf)
        print(f"[MQTT] Fotoğraf kaydedildi: {filepath}")
    except Exception as e:
        print("[FS] Foto kaydetme hatası:", e)
        return

    # DB güncelle
    try:
        conn = get_db(); c = conn.cursor()
        record_id = pending_photos.get(cam_device_id)
        print("[MQTT] Beklenen kayıt ID'si:", pending_photos.get(cam_device_id))
        if record_id:
            c.execute("UPDATE sensor_data SET image_path = ? WHERE id = ?", (filename, record_id))
            conn.commit()
            del pending_photos[cam_device_id]  # işin bitti, sil
        else:
            print("[MQTT] Uygun eşleşme bulunamadı, image_path güncellenemedi.")
    finally:
        conn.close()

    # HTTP POST
    try:
        resp = requests.post(HTTP_SERVER, data=fb_buf,
                             headers={"Content-Type": "image/jpeg"})
        print(f"[HTTP] Upload yanıtı: {resp.status_code}")
    except Exception as e:
        print("[HTTP] Upload hatası:", e)

    # WebSocket bildirimi
    notify_clients({
        "id":           record_id,
        "fcnt":         None,
        "timestamp":    time.strftime('%Y-%m-%d %H:%M:%S'),
        "device_id":    cam_device_id,
        "probe_id":     None,
        "manual_value": None,
        "remote_value": None,
        "image_path":   url_path
    })
    print("[MQTT] Dashboard’a fotoğraf bildirimi gönderildi.")



def start_mqtt():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    print("[MQTT] Broker’a bağlanılıyor…")
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_forever()


def start_mqtt_thread():
    t = threading.Thread(target=start_mqtt, daemon=True)
    t.start()
    print("[MQTT] Dinleme thread’i başlatıldı.")
