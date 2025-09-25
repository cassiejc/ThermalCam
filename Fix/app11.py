#Versi ada FPS display + Latency, ini yang terakhir run di thermal_monitoringV18_OptimisedV3
import cv2
import numpy as np
import datetime
import csv
import requests
import pandas as pd
import os
import json
import time
import socket
import struct
import threading
from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
import base64

# Import scipy untuk noise reduction (optional)
try:
    from scipy.ndimage import gaussian_filter
    SCIPY_AVAILABLE = True
except ImportError:
    print("Warning: scipy not installed, noise reduction will be limited")
    SCIPY_AVAILABLE = False

# Import InfluxDB
try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
    INFLUXDB_AVAILABLE = True
except ImportError:
    print("Warning: influxdb-client not installed, InfluxDB logging disabled")
    INFLUXDB_AVAILABLE = False

# ========== TAMBAHAN: File untuk menyimpan konfigurasi ESP32 ==========
ESP32_CONFIG_FILE = "data/esp32_config.json"

# Konfigurasi ESP32 Thermal Camera (default values, akan di-override dari file)
DEFAULT_ESP32_HOST = "192.168.1.100"  # Default jika belum pernah dikonfigurasi
DEFAULT_ESP32_PORT = 3333            # Default port

# Global variables untuk ESP32 config (akan diload dari file)
ESP32_HOST = DEFAULT_ESP32_HOST
ESP32_PORT = DEFAULT_ESP32_PORT

# Konfigurasi
default_threshold_value = 80  # Threshold default untuk thermal real (50°C)
csv_filename = "data/log_suhu.csv"

# ========== TAMBAHAN: File untuk menyimpan monitoring objects ==========
MONITORING_OBJECTS_FILE = "data/monitoring_objects.json"

# Konfigurasi Whatsapp Bot API
WWEBJS_BOT_URL = "http://localhost:3000" # URL API whatsapp-web.js

# File CSV yang berisi daftar nomor WhatsApp dan grup
CSV_NOMOR_WA = "data/daftar_nomor_wa.csv"
CSV_GROUP_WA = "data/daftar_group_wa.csv"

# Direktori untuk menyimpan screenshot
SCREENSHOT_DIR = "data/screenshots"

# Konfigurasi InfluxDB
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = "OdSIh300WDGvBL8uPnaP4A54R4wA1k7h7sMnpGuNJVMlHJ9omObxdx0NaJ5NFXL7aE8TK4c8rVSbiOLwZEmgGw=="
INFLUXDB_ORG = "cpkrian"
INFLUXDB_BUCKET = "thermal"

# ========== TAMBAHAN: Konfigurasi Auto-Restart Kamera ==========
ENABLE_AUTO_RESTART = True  # Set ke True untuk mengaktifkan, False untuk menonaktifkan
AUTO_RESTART_INTERVAL_MINUTES = 11 # Interval dalam menit
# <--- TAMBAHAN: Konfigurasi untuk menyalakan kamera otomatis saat program berjalan
AUTO_START_ON_BOOT = True

# Variabel global untuk monitoring
MONITORING_MODES = {
    'BBOX': 'Bounding Box',
    'LINE': 'Line',
    'POINT': 'Point',
    'POLYGON': 'Polygon',
    'CURSOR': 'Free Cursor'
}

current_mode = 'BBOX'
monitoring_objects = []
area_counter = 1
camera_active = False
cap = None
cursor_temp_enabled = False

# ========== TAMBAHAN: Variabel untuk melacak koneksi browser ==========
active_clients = 0

# ========== TAMBAHAN: Mirror/flip video stream ==========
mirror_enabled = True

# ========== TAMBAHAN: Colormap configuration ==========
current_colormap = cv2.COLORMAP_INFERNO  # Default colormap

# Dictionary colormap yang tersedia
AVAILABLE_COLORMAPS = {
    'INFERNO': cv2.COLORMAP_INFERNO,
    'PLASMA': cv2.COLORMAP_PLASMA,
    'VIRIDIS': cv2.COLORMAP_VIRIDIS,
    'JET': cv2.COLORMAP_JET,
    'HOT': cv2.COLORMAP_HOT,
    'COOL': cv2.COLORMAP_COOL,
    'RAINBOW': cv2.COLORMAP_RAINBOW,
    'OCEAN': cv2.COLORMAP_OCEAN,
    'SPRING': cv2.COLORMAP_SPRING,
    'SUMMER': cv2.COLORMAP_SUMMER,
    'AUTUMN': cv2.COLORMAP_AUTUMN,
    'WINTER': cv2.COLORMAP_WINTER,
    'BONE': cv2.COLORMAP_BONE,
    'PINK': cv2.COLORMAP_PINK,
    'HSV': cv2.COLORMAP_HSV,
    'PARULA': cv2.COLORMAP_PARULA
}

# ========== TAMBAHAN: Fungsi untuk save/load monitoring objects ==========
def save_monitoring_objects():
    """Simpan monitoring objects ke file JSON"""
    try:
        os.makedirs(os.path.dirname(MONITORING_OBJECTS_FILE), exist_ok=True)

        # Prepare data untuk disimpan
        save_data = {
            'objects': monitoring_objects,
            'area_counter': area_counter,
            'default_threshold': default_threshold_value,
            'timestamp': datetime.datetime.now().isoformat()
        }

        with open(MONITORING_OBJECTS_FILE, 'w') as f:
            json.dump(save_data, f, indent=2)

        print(f"✅ Monitoring objects saved to {MONITORING_OBJECTS_FILE}")
        return True
    except Exception as e:
        print(f"❌ Error saving monitoring objects: {e}")
        return False

def load_monitoring_objects():
    """Load monitoring objects dari file JSON"""
    global monitoring_objects, area_counter, default_threshold_value

    try:
        if not os.path.exists(MONITORING_OBJECTS_FILE):
            print(f"📄 No monitoring objects file found at {MONITORING_OBJECTS_FILE}")
            return False

        with open(MONITORING_OBJECTS_FILE, 'r') as f:
            data = json.load(f)

        # Load data
        monitoring_objects = data.get('objects', [])
        area_counter = data.get('area_counter', 1)
        loaded_threshold = data.get('default_threshold', default_threshold_value)

        # Update area_counter untuk object baru
        if monitoring_objects:
            # Cari counter tertinggi dari nama object yang ada
            max_counter = 0
            for obj in monitoring_objects:
                name = obj.get('name', '')
                # Ekstrak angka dari nama seperti "BBOX 1", "LINE 2", etc
                for part in name.split():
                    if part.isdigit():
                        max_counter = max(max_counter, int(part))
            area_counter = max_counter + 1

        print(f"✅ Loaded {len(monitoring_objects)} monitoring objects")
        print(f"📊 Area counter: {area_counter}")
        print(f"🌡️  Default threshold: {loaded_threshold}°C")

        # Print detail objects yang di-load
        for i, obj in enumerate(monitoring_objects):
            print(f"   {i+1}. {obj['name']} ({obj['type']}) - Threshold: {obj.get('threshold', default_threshold_value)}°C")

        return True

    except Exception as e:
        print(f"❌ Error loading monitoring objects: {e}")
        return False

# ========== TAMBAHAN: Fungsi untuk save/load ESP32 config ==========
def save_esp32_config():
    """Simpan konfigurasi ESP32 ke file JSON"""
    try:
        os.makedirs(os.path.dirname(ESP32_CONFIG_FILE), exist_ok=True)

        # Load existing config atau buat baru
        config_data = {}
        if os.path.exists(ESP32_CONFIG_FILE):
            try:
                with open(ESP32_CONFIG_FILE, 'r') as f:
                    config_data = json.load(f)
            except:
                config_data = {}

        # Update ESP32 config
        config_data.update({
            'host': ESP32_HOST,
            'port': ESP32_PORT,
            'timestamp': datetime.datetime.now().isoformat()
        })

        with open(ESP32_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)

        print(f"✅ ESP32 config saved: {ESP32_HOST}:{ESP32_PORT}")
        return True
    except Exception as e:
        print(f"❌ Error saving ESP32 config: {e}")
        return False

def load_esp32_config():
    """Load konfigurasi ESP32 dari file JSON"""
    global ESP32_HOST, ESP32_PORT

    try:
        if not os.path.exists(ESP32_CONFIG_FILE):
            print(f"📄 No ESP32 config file found, using defaults: {DEFAULT_ESP32_HOST}:{DEFAULT_ESP32_PORT}")
            ESP32_HOST = DEFAULT_ESP32_HOST
            ESP32_PORT = DEFAULT_ESP32_PORT
            return False

        with open(ESP32_CONFIG_FILE, 'r') as f:
            config_data = json.load(f)

        ESP32_HOST = config_data.get('host', DEFAULT_ESP32_HOST)
        ESP32_PORT = config_data.get('port', DEFAULT_ESP32_PORT)

        print(f"✅ ESP32 config loaded: {ESP32_HOST}:{ESP32_PORT}")
        return True

    except Exception as e:
        print(f"❌ Error loading ESP32 config: {e}")
        print(f"Using defaults: {DEFAULT_ESP32_HOST}:{DEFAULT_ESP32_PORT}")
        ESP32_HOST = DEFAULT_ESP32_HOST
        ESP32_PORT = DEFAULT_ESP32_PORT
        return False

# ========== TAMBAHAN: Fungsi untuk save/load colormap config ==========
def save_colormap_config():
    """Simpan konfigurasi colormap ke file JSON"""
    try:
        # Cari nama colormap dari value
        colormap_name = 'INFERNO'  # default
        for name, value in AVAILABLE_COLORMAPS.items():
            if value == current_colormap:
                colormap_name = name
                break

        # Load existing config atau buat baru
        config_data = {}
        if os.path.exists(ESP32_CONFIG_FILE):
            try:
                with open(ESP32_CONFIG_FILE, 'r') as f:
                    config_data = json.load(f)
            except:
                config_data = {}

        # Update colormap config
        config_data.update({
            'colormap': colormap_name,
            'timestamp': datetime.datetime.now().isoformat()
        })

        os.makedirs(os.path.dirname(ESP32_CONFIG_FILE), exist_ok=True)
        with open(ESP32_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)

        print(f"✅ Colormap config saved: {colormap_name}")
        return True
    except Exception as e:
        print(f"❌ Error saving colormap config: {e}")
        return False

def load_colormap_config():
    """Load konfigurasi colormap dari file JSON"""
    global current_colormap

    try:
        if os.path.exists(ESP32_CONFIG_FILE):
            with open(ESP32_CONFIG_FILE, 'r') as f:
                config_data = json.load(f)

            colormap_name = config_data.get('colormap', 'INFERNO')
            current_colormap = AVAILABLE_COLORMAPS.get(colormap_name, cv2.COLORMAP_INFERNO)
            print(f"✅ Colormap config loaded: {colormap_name}")
            return True
    except Exception as e:
        print(f"❌ Error loading colormap config: {e}")

    # Set default jika gagal load
    current_colormap = cv2.COLORMAP_INFERNO
    print(f"📄 Using default colormap: INFERNO")
    return False

# Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'thermal_monitoring_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Inisialisasi InfluxDB Client
influx_client = None
influx_write_api = None

if INFLUXDB_AVAILABLE:
    try:
        influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        influx_write_api = influx_client.write_api(write_options=SYNCHRONOUS)
        print("Koneksi ke InfluxDB berhasil.")
    except Exception as e:
        influx_client = None
        influx_write_api = None
        print(f"Gagal koneksi ke InfluxDB: {e}")
        print("Data overheat tidak akan disimpan ke InfluxDB.")
else:
    print("InfluxDB client tidak tersedia - install dengan: pip install influxdb-client")

def simpan_ke_influxdb(nama_objek, suhu, status):
    """
    Menyimpan data ke InfluxDB: timestamp, nama objek, suhu, dan status.
    """
    if not influx_write_api:
        return

    try:
        point = Point("temperature") \
            .tag("object_name", nama_objek) \
            .tag("status", status) \
            .field("value", float(suhu)) \
            .time(datetime.datetime.utcnow())

        influx_write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)

    except Exception as e:
        print(f"Gagal menyimpan data ke InfluxDB: {e}")

def save_thermal_screenshot(frame, overheat_objects):
    """
    Simpan screenshot thermal dengan informasi overheat
    DIPERBAIKI: Gunakan frame yang sudah memiliki visual overlay
    """
    try:
        # Pastikan direktori screenshot ada
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        # Generate filename dengan timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"thermal_alert_{timestamp}.jpg"
        filepath = os.path.join(SCREENSHOT_DIR, filename)

        # Frame sudah memiliki visual overlay, langsung simpan
        # Tidak perlu copy dan annotasi lagi
        cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

        print(f"Screenshot saved: {filepath}")
        return filepath

    except Exception as e:
        print(f"Error saving screenshot: {e}")
        return None

def get_whatsapp_recipients():
    recipients = {'personal': [], 'groups': []}
    try:
        if os.path.exists(CSV_NOMOR_WA):
            df_nomor = pd.read_csv(CSV_NOMOR_WA)
            recipients['personal'] = df_nomor['Nomor_WhatsApp'].astype(str).str.strip().tolist()
        if os.path.exists(CSV_GROUP_WA):
            df_group = pd.read_csv(CSV_GROUP_WA)
            recipients['groups'] = df_group['Group_ID'].astype(str).str.strip().tolist()
    except Exception as e:
        print(f"Error reading WhatsApp recipients: {e}")
    return recipients

def get_whatsapp_recipients():
    """Mendapatkan daftar penerima (personal & grup) dari file CSV."""
    recipients = {'personal': [], 'groups': []}
    try:
        if os.path.exists(CSV_NOMOR_WA):
            df_nomor = pd.read_csv(CSV_NOMOR_WA)
            recipients['personal'] = df_nomor['Nomor_WhatsApp'].astype(str).str.strip().tolist()
        if os.path.exists(CSV_GROUP_WA):
            df_group = pd.read_csv(CSV_GROUP_WA)
            recipients['groups'] = df_group['Group_ID'].astype(str).str.strip().tolist()
    except Exception as e:
        print(f"Error reading WhatsApp recipients: {e}")
    return recipients

def kirim_notifikasi_whatsapp(recipients, message, image_path=None):
    """
    Fungsi DIPERBAIKI: Mengirim notifikasi dan memeriksa status keberhasilan
    dengan lebih andal.
    """
    headers = {"Content-Type": "application/json"}
    any_success = False  # Gunakan flag boolean, bukan counter
    personal_targets = recipients.get('personal', [])
    group_targets = recipients.get('groups', [])

    try:
        # KASUS 1: Jika ada gambar, kirim sebagai gambar dengan pesan detail sebagai caption.
        if image_path and os.path.exists(image_path):
            abs_image_path = os.path.abspath(image_path)

            # Kirim ke nomor personal (jika ada)
            if personal_targets:
                payload = {
                    "numbers": personal_targets,
                    "imagePath": abs_image_path,
                    "caption": message
                }
                response = requests.post(f"{WWEBJS_BOT_URL}/sendImage", json=payload, headers=headers, timeout=60)
                if response.status_code == 200:
                    any_success = True # Tandai sebagai sukses jika status 200 OK
                    print(f"✅ Notifikasi gambar dalam antrian untuk dikirim ke personal.")
                else:
                    print(f"❌ Gagal mengirim gambar ke personal: {response.text}")

            # Kirim ke grup (jika ada)
            if group_targets:
                payload = {
                    "groupIds": group_targets,
                    "imagePath": abs_image_path,
                    "caption": message
                }
                response = requests.post(f"{WWEBJS_BOT_URL}/sendImageToGroup", json=payload, headers=headers, timeout=60)
                if response.status_code == 200:
                    any_success = True # Tandai sebagai sukses jika status 200 OK
                    print(f"✅ Notifikasi gambar dalam antrian untuk dikirim ke grup.")
                else:
                    print(f"❌ Gagal mengirim gambar ke grup: {response.text}")

        # KASUS 2: Jika tidak ada gambar, kirim sebagai pesan teks biasa.
        elif message and (personal_targets or group_targets):
            payload = {
                "numbers": personal_targets,
                "groupIds": group_targets,
                "text": message
            }
            response = requests.post(f"{WWEBJS_BOT_URL}/sendText", json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                any_success = True # Tandai sebagai sukses jika status 200 OK
                print(f"✅ Pesan teks dalam antrian untuk dikirim.")
            else:
                print(f"❌ Gagal mengirim pesan teks: {response.text}")

        return any_success

    except requests.exceptions.RequestException as e:
        print(f"Gagal menghubungi WhatsApp Bot API: {e}")
        return False
    except Exception as e:
        print(f"Error saat mengirim WhatsApp: {e}")
        return False

def kirim_pesan_ke_semua_kontak(overheat_objects, timestamp, thermal_frame=None):
    """
    Fungsi ini sekarang memanggil `kirim_notifikasi_whatsapp` yang sudah diperbaiki.
    """
    recipients = get_whatsapp_recipients()
    if not recipients['personal'] and not recipients['groups']:
        print("Tidak ada nomor WA atau grup yang terdaftar!")
        return False

    object_list = [f"• {obj['name']}: {obj['temp']:.1f}°C (Batas: {obj['threshold']}°C)" for obj in overheat_objects]
    objects_text = "\n".join(object_list)
    # Pesan ini sekarang akan menjadi caption jika ada gambar
    pesan = (
        f"*🚨 ALERT SUHU TINGGI 🚨*\n"
        f"Waktu: {timestamp}\n\n"
        f"Objek yang mengalami overheat:\n{objects_text}\n\n"
        f"Segera lakukan pengecekan!"
    )

    screenshot_path = None
    if thermal_frame is not None:
        try:
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"thermal_alert_{ts}.jpg"
            screenshot_path = os.path.join(SCREENSHOT_DIR, filename)
            cv2.imwrite(screenshot_path, thermal_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            print(f"Screenshot saved: {screenshot_path}")
        except Exception as e:
            print(f"Error saving screenshot: {e}")

    # Memanggil fungsi notifikasi yang sudah diperbaiki
    return kirim_notifikasi_whatsapp(recipients, pesan, screenshot_path)


def test_wwebjs_bot_connection():
    """Test koneksi ke API whatsapp-web.js."""
    try:
        response = requests.get(f"{WWEBJS_BOT_URL}/status", timeout=5)
        return response.status_code == 200 and response.json().get('client_ready', False)
    except:
        return False

def get_wwebjs_bot_groups():
    """Mendapatkan daftar grup dari API whatsapp-web.js."""
    try:
        response = requests.get(f"{WWEBJS_BOT_URL}/getGroups", timeout=10)
        if response.status_code == 200:
            return response.json().get('groups', [])
        return []
    except:
        return []

# ESP32 Thermal Monitor Class
class ESP32ThermalMonitor:
    def __init__(self, esp32_host=ESP32_HOST, esp32_port=ESP32_PORT):
        self.esp32_host = esp32_host
        self.esp32_port = esp32_port
        self.socket = None
        self.running = False
        self.frame = None
        self.thermal_frame = None
        self.max_temp_global = 0
        self.overheat_objects = []
        self.cursor_pos = None
        self.cursor_temp = 0

        # ========== TAMBAHAN: Lacak objek untuk konfirmasi overheat ==========
        self.potential_overheat_tracker = {}  # Format: {'nama_objek': timestamp_pertama_terdeteksi}
        self.OVERHEAT_CONFIRMATION_DURATION_SECONDS = 30  # Durasi konfirmasi: 5 detik

        self.confirmed_overheat_states = {} # Format: {'nama_objek': True}


        # ========== PERBAIKAN: Per-Object Notification Tracking ==========
        self.object_last_notification = {}  # {object_name: timestamp}
        self.object_notification_cooldown = 300  # 5 menit per objek (300 detik)

        # ========== PERBAIKAN: Processing Interval Control ==========
        self.last_process_time = 0
        self.process_interval = 0.04  # Process setiap 0.05 detik untuk real-time display

        # ========== SMART LOGGING: Interval terpisah untuk logging ==========
        self.normal_log_interval = 300   # 20 menit saat normal
        self.alert_log_interval = 300      # 1 menit saat overheat
        self.last_log_time = 0

        # ========== PERBAIKAN: Debugging & Logging ==========
        self.notification_log = []  # Log untuk debugging

        # ESP32 thermal camera constants
        self.FRAME_WIDTH = 80
        self.FRAME_HEIGHT = 62
        self.RAW_FRAME_SIZE = self.FRAME_WIDTH * self.FRAME_HEIGHT * 2  # 2 bytes per pixel
        self.STRIP_HEAD = 160
        self.STRIP_TAIL = 160
        self.TCP_FRAME_SIZE = self.RAW_FRAME_SIZE + self.STRIP_HEAD + self.STRIP_TAIL

        self.receive_buffer = b''
        self.connection_thread = None
        self.reconnect_delay = 3.0

        #TAMBAHAN: Background processing thread
        self.background_thread = None
        self.background_running = False

        #TAMBAHAN: Separate flags untuk display vs logging
        self.enable_background_processing = True  # Untuk logging otomatis
        self.enable_display_processing = True     # Untuk tampilan video

        # ========== TAMBAHAN: Variabel untuk kalkulasi FPS ==========
        self.frame_counter = 0
        self.fps_start_time = time.time()
        self.processing_fps = 0
        self.fps_thread = None

    def should_log_data(self):
        """Cek apakah sudah waktunya logging (terpisah dari processing)"""
        current_time = time.time()
        time_since_last_log = current_time - self.last_log_time

        # Tentukan interval berdasarkan kondisi overheat
        if self.overheat_objects:
            required_interval = self.alert_log_interval
        else:
            required_interval = self.normal_log_interval

        return time_since_last_log >= required_interval

    def log_data_to_storage(self):
        """Logging terpisah - frekuensi berbeda dari processing"""
        try:
            for obj in monitoring_objects:
                obj_threshold = obj.get('threshold', default_threshold_value)
                status = "OVERHEAT" if obj['temp'] >= obj_threshold else "NORMAL"

                # Simpan ke CSV
                with open(csv_filename, mode='a', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow([
                        datetime.datetime.now(),
                        obj['name'],
                        obj['type'],
                        f"{obj['temp']:.2f}",
                        obj_threshold,
                        status
                    ])

                # Simpan ke InfluxDB
                simpan_ke_influxdb(obj['name'], obj['temp'], status)

            # Update waktu logging terakhir
            self.last_log_time = time.time()

            # Info logging dengan interval yang digunakan
            interval_used = self.alert_log_interval if self.overheat_objects else self.normal_log_interval

            print(f"📊 Data logged (interval: {interval_used}s, objects: {len(monitoring_objects)})")

        except Exception as e:
            print(f"❌ Error logging data: {e}")

    def connect_to_esp32(self):
        """Koneksi ke ESP32 thermal camera via TCP"""
        try:
            if self.socket:
                self.socket.close()

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10)  # 10 second timeout

            print(f"Mencoba koneksi ke ESP32 di {self.esp32_host}:{self.esp32_port}")
            self.socket.connect((self.esp32_host, self.esp32_port))
            print(f"Berhasil terhubung ke ESP32")

            # Reset buffer
            self.receive_buffer = b''
            return True

        except Exception as e:
            print(f"Gagal koneksi ke ESP32: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False

    def start_camera(self):
        """Mulai thermal camera ESP32 dengan background processing"""
        if self.connect_to_esp32():
            self.running = True

            # Start connection thread untuk receive data
            self.connection_thread = threading.Thread(target=self._receive_data_thread, daemon=True)
            self.connection_thread.start()

            # ========== TAMBAHAN: Start background processing thread ==========
            if self.enable_background_processing:
                self.start_background_processing()

            # ========== TAMBAHAN: Start FPS calculation thread ==========
            self.fps_thread = threading.Thread(target=self._calculate_fps_loop, daemon=True)
            self.fps_thread.start()

            return True
        return False

    def stop_camera(self):
        """Hentikan thermal camera ESP32"""
        self.running = False

        # ========== TAMBAHAN: Stop background processing ==========
        self.stop_background_processing()

        if self.socket:
            self.socket.close()
            self.socket = None
        if self.connection_thread:
            self.connection_thread.join(timeout=2)
        if self.fps_thread:
            self.fps_thread.join(timeout=1)

    def start_background_processing(self):
        """Start background thread untuk processing dan logging otomatis"""
        if not self.background_running:
            self.background_running = True
            self.background_thread = threading.Thread(target=self._background_processing_loop, daemon=True)
            self.background_thread.start()
            print("Background processing thread started")

    def stop_background_processing(self):
        """Stop background processing thread"""
        self.background_running = False
        if self.background_thread:
            self.background_thread.join(timeout=3)
            print("Background processing thread stopped")

    def _background_processing_loop(self):
        """Background loop untuk processing dan logging secara independen"""
        print("🚀 Background processing loop started - sistem akan terus berjalan tanpa browser")

        while self.background_running and self.running:
            try:
                # Process frame untuk monitoring dan logging (tanpa generate visual)
                self._process_frame_for_logging()

                # Sleep sebentar untuk mencegah CPU overload
                time.sleep(0.1)  # 10 FPS untuk background processing

            except Exception as e:
                print(f"❌ Error in background processing: {e}")
                time.sleep(1)
                continue


    def _receive_data_thread(self):
        """Thread untuk menerima data dari ESP32"""
        while self.running and self.socket:
            try:
                data = self.socket.recv(4096)
                if not data:
                    print("Koneksi ESP32 terputus")
                    break

                self.receive_buffer += data

                # Process complete frames
                while len(self.receive_buffer) >= self.TCP_FRAME_SIZE:
                    # Extract thermal frame (skip header and tail)
                    thermal_data = self.receive_buffer[self.STRIP_HEAD:self.STRIP_HEAD + self.RAW_FRAME_SIZE]

                    # Convert raw bytes to temperature array
                    self._process_thermal_data(thermal_data)
                    self.frame_counter += 1

                    # Remove processed frame from buffer
                    self.receive_buffer = self.receive_buffer[self.TCP_FRAME_SIZE:]

            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving data: {e}")
                break

        # Reconnect logic
        if self.running:
            print("Mencoba reconnect ke ESP32...")
            time.sleep(self.reconnect_delay)
            if self.running:
                self.connect_to_esp32()

    def _process_thermal_data(self, thermal_data):
        """Proses data thermal mentah dari ESP32"""
        try:
            # Convert bytes to 16-bit unsigned integers (little endian)
            temp_array = np.frombuffer(thermal_data, dtype=np.uint16)

            # Reshape to 2D array (80x62)
            temp_2d = temp_array.reshape(self.FRAME_HEIGHT, self.FRAME_WIDTH)

            # Konversi dari raw ADC values ke temperature Celsius
            temp_celsius = self._raw_to_celsius(temp_2d)

            # Update frame data
            self.frame = temp_celsius

        except Exception as e:
            print(f"Error processing thermal data: {e}")

    def _raw_to_celsius(self, raw_data):
        # Konversi formula
        temp_celsius = raw_data.astype(np.float32) * 0.0984 - 265.82

        # Apply noise reduction jika scipy tersedia
        if SCIPY_AVAILABLE and temp_celsius.ndim == 2:
            temp_celsius = gaussian_filter(temp_celsius, sigma=0.5)  # Slightly more filtering

        # Clip temperature ke range yang masuk akal untuk thermal camera
        temp_celsius = np.clip(temp_celsius, -20, 400)
        # temp_celsius = np.clip(temp_celsius, 30, 40)

        print(f"ESP32 Thermal - Temperature range: {np.min(temp_celsius):.1f}oC to {np.max(temp_celsius):.1f}oC")

        return temp_celsius.astype(np.float32)

    def calculate_line_temperature(self, temp_image, start_point, end_point):
        """Hitung suhu rata-rata dan maksimum sepanjang garis"""
        x1, y1 = start_point
        x2, y2 = end_point

        num_points = max(abs(x2 - x1), abs(y2 - y1))
        if num_points == 0:
            return temp_image[y1, x1] if 0 <= y1 < temp_image.shape[0] and 0 <= x1 < temp_image.shape[1] else 0

        x_coords = np.linspace(x1, x2, num_points).astype(int)
        y_coords = np.linspace(y1, y2, num_points).astype(int)

        valid_indices = (
            (x_coords >= 0) & (x_coords < temp_image.shape[1]) &
            (y_coords >= 0) & (y_coords < temp_image.shape[0])
        )

        if not np.any(valid_indices):
            return 0

        x_coords = x_coords[valid_indices]
        y_coords = y_coords[valid_indices]

        line_temps = temp_image[y_coords, x_coords]
        return float(np.max(line_temps))

    def get_point_temperature(self, temp_image, point):
        """Ambil suhu di titik tertentu"""
        x, y = point
        if 0 <= y < temp_image.shape[0] and 0 <= x < temp_image.shape[1]:
            return float(temp_image[y, x])
        return 0

    def calculate_polygon_temperature(self, temp_image, polygon_points):
        """Hitung suhu maksimum dalam area polygon"""
        if len(polygon_points) < 3:
            return 0

        # Convert points to numpy array
        points = np.array(polygon_points, dtype=np.int32)

        # Create mask for polygon area
        mask = np.zeros(temp_image.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [points], 255)

        # Get temperatures within polygon area
        masked_temps = temp_image[mask > 0]

        if len(masked_temps) > 0:
            return float(np.max(masked_temps))
        else:
            return 0

    # ========== PERBAIKAN: Method untuk logging notifikasi ==========
    def _log_notification(self, action, obj_name, temp, threshold):
        """Log aktivitas notifikasi untuk debugging"""
        log_entry = {
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'object_name': obj_name,
            'temperature': temp,
            'threshold': threshold
        }
        self.notification_log.append(log_entry)

        # Keep only last 50 entries
        if len(self.notification_log) > 50:
            self.notification_log = self.notification_log[-50:]

        print(f"[NOTIFICATION LOG] {action}: {obj_name} - {temp:.1f}oC (threshold: {threshold}oC)")

    def generate_notification_screenshot(self, overheat_objects):
            """
            Generate screenshot khusus untuk notifikasi dengan visual overlay sederhana
            """
            if self.frame is None:
                return None

            try:
                # ========== GENERATE THERMAL VISUAL DISPLAY ==========
                temp_frame = self.frame
                temp_min = np.min(temp_frame)
                temp_max = np.max(temp_frame)

                if temp_max > temp_min:
                    normalized = ((temp_frame - temp_min) / (temp_max - temp_min) * 255).astype(np.uint8)
                else:
                    normalized = np.zeros_like(temp_frame, dtype=np.uint8)

                # Apply colormap
                thermal_display = cv2.applyColorMap(normalized, current_colormap)
                thermal_display = cv2.resize(thermal_display, (640, 480), interpolation=cv2.INTER_LINEAR )
                temp_frame_resized = cv2.resize(temp_frame, (640, 480), interpolation=cv2.INTER_LINEAR )

                # Mirror jika enabled
                if mirror_enabled:
                    thermal_display = cv2.flip(thermal_display, 1)
                    temp_frame_resized = cv2.flip(temp_frame_resized, 1)

                # ========== TAMBAHKAN COLORBAR ==========
                scale_width = 20
                scale_height = 200
                scale_x = thermal_display.shape[1] - scale_width - 65
                scale_y = 50

                scale_gradient = np.linspace(255, 0, scale_height).astype(np.uint8)
                scale_gradient = np.repeat(scale_gradient[:, np.newaxis], scale_width, axis=1)
                scale_colored = cv2.applyColorMap(scale_gradient, current_colormap)

                cv2.rectangle(thermal_display, (scale_x-2, scale_y-2),
                                (scale_x+scale_width+2, scale_y+scale_height+2), (255, 255, 255), 2)
                thermal_display[scale_y:scale_y+scale_height, scale_x:scale_x+scale_width] = scale_colored

                # Temperature labels untuk colorbar
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.4
                thickness = 1

                def put_temp_label(img, value, x, y):
                    text = f"{value:.1f}oC"
                    cv2.putText(img, text, (x, y), font, font_scale, (0,0,0), thickness+1)
                    cv2.putText(img, text, (x, y), font, font_scale, (255,255,255), thickness)

                put_temp_label(thermal_display, temp_max, scale_x + scale_width + 5, scale_y + 5)
                put_temp_label(thermal_display, temp_min, scale_x + scale_width + 5, scale_y + scale_height)
                put_temp_label(thermal_display, (temp_max + temp_min) / 2, scale_x + scale_width + 5, scale_y + scale_height//2)

                # ========== GAMBAR SEMUA MONITORING OBJECTS ==========
                for obj in monitoring_objects:
                    obj_type = obj['type']
                    nama_objek = obj['name']
                    coords = obj['coords']
                    obj_threshold = obj.get('threshold', default_threshold_value)
                    max_temp = obj.get('temp', 0)

                    # Tentukan warna: MERAH untuk overheat, HIJAU untuk normal
                    is_overheat = max_temp >= obj_threshold
                    color = (0, 0, 255) if is_overheat else (80, 200, 120)  # BGR format
                    line_thickness = 2

                    # ========== GAMBAR BERDASARKAN TIPE OBJECT ==========
                    if obj_type == 'BBOX':
                        x, y, w, h = coords
                        x = max(0, min(x, thermal_display.shape[1] - 1))
                        y = max(0, min(y, thermal_display.shape[0] - 1))
                        w = min(w, thermal_display.shape[1] - x)
                        h = min(h, thermal_display.shape[0] - y)

                        if w > 0 and h > 0:
                            # Gambar rectangle
                            cv2.rectangle(thermal_display, (x, y), (x+w, y+h), color, line_thickness)

                            # Label sederhana hanya untuk overheat objects
                            if is_overheat:
                                label_y = y - 10 if y > 15 else y + h + 15
                                label_x = x + 5
                                temp_text = f"{nama_objek}: {max_temp:.1f}oC"
                                cv2.putText(thermal_display, temp_text, (label_x, label_y),
                                            font, 0.5, (255, 255, 255), 1)

                    elif obj_type == 'LINE':
                        start_pt, end_pt = coords
                        cv2.line(thermal_display, tuple(start_pt), tuple(end_pt), color, line_thickness)

                        # Label hanya untuk overheat
                        if is_overheat:
                            mid_x, mid_y = (start_pt[0] + end_pt[0]) // 2, (start_pt[1] + end_pt[1]) // 2
                            temp_text = f"{nama_objek}: {max_temp:.1f}oC"
                            cv2.putText(thermal_display, temp_text, (mid_x, mid_y),
                                        font, 0.5, (255, 255, 255), 1)

                    elif obj_type == 'POINT':
                        point_x, point_y = coords
                        radius = 5
                        cv2.circle(thermal_display, (point_x, point_y), radius, color, -1)

                        # Label hanya untuk overheat
                        if is_overheat:
                            temp_text = f"{nama_objek}: {max_temp:.1f}oC"
                            label_x, label_y = point_x + 10, point_y - 5
                            cv2.putText(thermal_display, temp_text, (label_x, label_y),
                                        font, 0.5, (255, 255, 255), 1)

                    elif obj_type == 'POLYGON':
                        if len(coords) >= 3:
                            points = np.array(coords, dtype=np.int32)
                            cv2.polylines(thermal_display, [points], True, color, line_thickness)

                            # Label hanya untuk overheat
                            if is_overheat:
                                centroid_x = int(np.mean([p[0] for p in coords]))
                                centroid_y = int(np.mean([p[1] for p in coords]))
                                temp_text = f"{nama_objek}: {max_temp:.1f}oC"
                                cv2.putText(thermal_display, temp_text,
                                            (centroid_x - 50, centroid_y), font, 0.5,
                                            (255, 255, 255), 1)

                # ========== TAMBAHKAN HEADER ==========
                # Main alert text
                cv2.putText(thermal_display, "!!! OVERHEAT ALERT !!!", (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
                # Timestamp
                timestamp_text = f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                cv2.putText(thermal_display, timestamp_text, (20, 65),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

                return thermal_display

            except Exception as e:
                print(f"Error generating notification screenshot: {e}")
                return None

    def _process_frame_for_logging(self):
        """
        Process frame khusus untuk logging - TIDAK menghasilkan visual display
        Fokus pada: monitoring objek, deteksi overheat, logging, notifikasi
        """
        if not self.running or self.frame is None:
            return

        current_time = time.time()

        # ========== LIMIT: Processing frequency untuk efisiensi ==========
        if (current_time - self.last_process_time) < self.process_interval:
            return

        self.last_process_time = current_time

        # Gunakan frame temperature yang sudah ada
        temp_frame = self.frame

        # Resize untuk consistency dengan display version
        temp_frame_resized = cv2.resize(temp_frame, (640, 480), interpolation=cv2.INTER_LINEAR )

        # Mirror jika enabled (untuk consistency dengan display)
        if mirror_enabled:
            temp_frame_resized = cv2.flip(temp_frame_resized, 1)

        # ========== RESET tracking variables ==========
        self.max_temp_global = 0
        self.overheat_objects = []

        # ========== PROSES MONITORING OBJECTS (SAMA SEPERTI SEBELUMNYA) ==========
        for obj in monitoring_objects:
            obj_type = obj['type']
            nama_objek = obj['name']
            coords = obj['coords']
            obj_threshold = obj.get('threshold', default_threshold_value)

            max_temp = 0

            # ========== HITUNG TEMPERATURE BERDASARKAN TIPE OBJECT ==========
            if obj_type == 'BBOX':
                x, y, w, h = coords
                x = max(0, min(x, temp_frame_resized.shape[1] - 1))
                y = max(0, min(y, temp_frame_resized.shape[0] - 1))
                w = min(w, temp_frame_resized.shape[1] - x)
                h = min(h, temp_frame_resized.shape[0] - y)

                if w > 0 and h > 0:
                    roi = temp_frame_resized[y:y+h, x:x+w]
                    if roi.size > 0:
                        max_temp = float(np.max(roi))

            elif obj_type == 'LINE':
                start_pt, end_pt = coords
                max_temp = self.calculate_line_temperature(temp_frame_resized, start_pt, end_pt)

            elif obj_type == 'POINT':
                point_x, point_y = coords
                max_temp = self.get_point_temperature(temp_frame_resized, (point_x, point_y))

            elif obj_type == 'POLYGON':
                polygon_points = coords
                valid_points = []
                for point in polygon_points:
                    x, y = point
                    x = max(0, min(x, temp_frame_resized.shape[1] - 1))
                    y = max(0, min(y, temp_frame_resized.shape[0] - 1))
                    valid_points.append([x, y])

                if len(valid_points) >= 3:
                    max_temp = self.calculate_polygon_temperature(temp_frame_resized, valid_points)

            # ========== UPDATE OBJECT TEMPERATURE ==========
            obj['temp'] = max_temp
            self.max_temp_global = max(self.max_temp_global, max_temp)

            # ========== DETEKSI OVERHEAT DENGAN KONFIRMASI 5 detik ==========
            # ========== DETEKSI OVERHEAT DENGAN KONFIRMASI & STATUS PERSISTEN ==========
            if max_temp >= obj_threshold:
                # Suhu terdeteksi di atas ambang batas.
                if nama_objek not in self.potential_overheat_tracker:
                    # Mulai timer jika ini deteksi pertama
                    print(f"🌡️  POTENTIAL OVERHEAT: '{nama_objek}' ({max_temp:.1f}°C). Memulai timer konfirmasi...")
                    self.potential_overheat_tracker[nama_objek] = current_time
                else:
                    # Timer sudah berjalan, cek durasi
                    first_detected_time = self.potential_overheat_tracker[nama_objek]
                    duration = current_time - first_detected_time

                    if duration >= self.OVERHEAT_CONFIRMATION_DURATION_SECONDS:
                        # Durasi terlampaui, KONFIRMASI OVERHEAT.
                        if not self.confirmed_overheat_states.get(nama_objek):
                            # Hanya proses sebagai 'overheat baru' jika belum tercatat
                            self.overheat_objects.append({
                                'name': nama_objek, 'type': obj_type, 'temp': max_temp, 'threshold': obj_threshold
                            })
                            print(f"🔥 CONFIRMED OVERHEAT: '{nama_objek}' terkonfirmasi panas.")

                        # Tandai status overheat sebagai persisten
                        self.confirmed_overheat_states[nama_objek] = {
                            'name': nama_objek,
                            'type': obj_type,
                            'temp': max_temp,
                            'threshold': obj_threshold
                        }
                        # Hapus dari tracker potensial karena sudah dikonfirmasi
                        if nama_objek in self.potential_overheat_tracker:
                            del self.potential_overheat_tracker[nama_objek]
            else:
                # Suhu kembali normal, batalkan semua status.
                if nama_objek in self.potential_overheat_tracker:
                    print(f"✅  NORMALIZED: '{nama_objek}' kembali normal sebelum terkonfirmasi.")
                    del self.potential_overheat_tracker[nama_objek]

                if nama_objek in self.confirmed_overheat_states:
                    print(f"✅  RECOVERED: '{nama_objek}' yang sebelumnya overheat kini telah pulih.")
                    del self.confirmed_overheat_states[nama_objek]

        # ========== NOTIFIKASI WHATSAPP ==========
        if self.overheat_objects:
            print(f"🔥 OVERHEAT DETECTED: {len(self.overheat_objects)} objects")

            objects_to_notify = []
            for obj in self.overheat_objects:
                obj_name = obj['name']
                obj_temp = obj['temp']
                obj_threshold = obj['threshold']

                last_notif_time = self.object_last_notification.get(obj_name, 0)
                time_since_last = current_time - last_notif_time

                self._log_notification("DETECTED", obj_name, obj_temp, obj_threshold)

                if time_since_last > self.object_notification_cooldown:
                    objects_to_notify.append(obj)
                    self.object_last_notification[obj_name] = current_time
                    self._log_notification("NOTIFICATION_SENT", obj_name, obj_temp, obj_threshold)

            # ========== KIRIM NOTIFIKASI DENGAN SCREENSHOT PROPER ==========
            if objects_to_notify:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    # ========== GENERATE SCREENSHOT DENGAN VISUAL OVERLAY ==========
                    notification_frame = self.generate_notification_screenshot(objects_to_notify)

                    if kirim_pesan_ke_semua_kontak(objects_to_notify, timestamp, notification_frame):
                        obj_names = [obj['name'] for obj in objects_to_notify]
                        print(f"✅ WhatsApp notification with proper screenshot sent (background): {obj_names}")
                    else:
                        print("❌ Failed to send WhatsApp notification (background)")
                except Exception as e:
                    print(f"❌ Error sending WhatsApp notification (background): {e}")

        # ========== LOGGING KE STORAGE ==========
        if self.should_log_data():
            self.log_data_to_storage()
            print(f"📊 Background logging: {len(monitoring_objects)} objects, max_temp: {self.max_temp_global:.1f}°C")


    def process_frame(self):
        """
        Process frame untuk DISPLAY - dipanggil hanya ketika ada video feed request
        Ini menghasilkan visual thermal display untuk browser
        """
        if not self.running or self.frame is None:
            return None

        # Jika background processing aktif, frame sudah diproses untuk logging
        # Kita hanya perlu generate visual display
        if self.background_running:
            return self._generate_visual_display()
        else:
            # Fallback: jika background processing tidak aktif, proses lengkap di sini
            return self._process_frame_complete()

    def _generate_visual_display(self):
            """Generate visual thermal display (dipanggil dari process_frame untuk browser)"""
            if self.frame is None:
                return None

            current_time = time.time()

            # ========== GENERATE THERMAL VISUAL SAMA SEPERTI KODE ASLI ==========
            temp_frame = self.frame

            # Normalize temperature untuk visualisasi
            temp_min = np.min(temp_frame)
            temp_max = np.max(temp_frame)

            if temp_max > temp_min:
                normalized = ((temp_frame - temp_min) / (temp_max - temp_min) * 255).astype(np.uint8)
            else:
                normalized = np.zeros_like(temp_frame, dtype=np.uint8)

            # Apply colormap
            thermal_display = cv2.applyColorMap(normalized, current_colormap)

            # Resize
            thermal_display = cv2.resize(thermal_display, (640, 480), interpolation=cv2.INTER_LINEAR )
            temp_frame_resized = cv2.resize(temp_frame, (640, 480), interpolation=cv2.INTER_LINEAR )

            # Mirror jika enabled
            if mirror_enabled:
                thermal_display = cv2.flip(thermal_display, 1)
                temp_frame_resized = cv2.flip(temp_frame_resized, 1)

            # ========== TAMBAHKAN COLORBAR ==========
            scale_width = 20
            scale_height = 200
            scale_x = thermal_display.shape[1] - scale_width - 65
            scale_y = 50

            scale_gradient = np.linspace(255, 0, scale_height).astype(np.uint8)
            scale_gradient = np.repeat(scale_gradient[:, np.newaxis], scale_width, axis=1)
            scale_colored = cv2.applyColorMap(scale_gradient, current_colormap)

            cv2.rectangle(thermal_display, (scale_x-2, scale_y-2),
                          (scale_x+scale_width+2, scale_y+scale_height+2), (255, 255, 255), 2)
            thermal_display[scale_y:scale_y+scale_height, scale_x:scale_x+scale_width] = scale_colored

            # ========== TEMPERATURE LABELS UNTUK COLORBAR ==========
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.4
            thickness = 1

            def put_temp_label(img, value, x, y, font, font_scale, color, thickness):
                text = f"{value:.1f}"
                cv2.putText(img, text, (x, y), font, font_scale, (0,0,0), thickness+1)
                cv2.putText(img, text, (x, y), font, font_scale, color, thickness)
                (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
                deg_font_scale = font_scale * 0.7
                deg_x = x + text_w + 2
                deg_y = y - int(text_h * 0.8)
                cv2.putText(img, "o", (deg_x, deg_y), font, deg_font_scale, (0,0,0), thickness+1)
                cv2.putText(img, "o", (deg_x, deg_y), font, deg_font_scale, color, thickness)
                cv2.putText(img, "C", (deg_x + 12, y), font, font_scale, (0,0,0), thickness+1)
                cv2.putText(img, "C", (deg_x + 12, y), font, font_scale, color, thickness)

            put_temp_label(thermal_display, temp_max, scale_x + scale_width + 5, scale_y + 5, font, font_scale, (255,255,255), thickness)
            put_temp_label(thermal_display, temp_min, scale_x + scale_width + 5, scale_y + scale_height, font, font_scale, (255,255,255), thickness)
            put_temp_label(thermal_display, (temp_max + temp_min) / 2, scale_x + scale_width + 5, scale_y + scale_height//2, font, font_scale, (255,255,255), thickness)

            # Tambahan: Title untuk scale bar
            title_label = "Heat Scale"
            cv2.putText(thermal_display, title_label, (scale_x - 10, scale_y - 10),
                        font, font_scale, (0, 0, 0), thickness + 1)  # Outline hitam
            cv2.putText(thermal_display, title_label, (scale_x - 10, scale_y - 10),
                        font, font_scale, (255, 255, 255), thickness)  # Text putih

            # ========== TAMPILKAN MONITORING OBJECTS (DENGAN SEMUA DETAIL) ==========
            font_obj = cv2.FONT_HERSHEY_SIMPLEX
            font_scale_obj = 0.35
            thickness_obj = 1

            # Draw monitoring objects dengan data yang sudah diproses di background
            for obj in monitoring_objects:
                obj_type = obj['type']
                nama_objek = obj['name']
                coords = obj['coords']
                obj_threshold = obj.get('threshold', default_threshold_value)
                max_temp = obj.get('temp', 0)  # Ambil dari data yang sudah diproses

                if obj_type == 'BBOX':
                    x, y, w, h = coords
                    color = (0, 0, 255) if max_temp >= obj_threshold else (80, 200, 120)
                    cv2.rectangle(thermal_display, (x, y), (x+w, y+h), color, 2)

                    # Label temperature dengan format lengkap seperti process_frame
                    try:
                        img_h, img_w = thermal_display.shape[:2]
                        MIN_LABEL_MARGIN = 5

                        if y-30 < MIN_LABEL_MARGIN:
                            nama_y = y + 15
                            temp_y = y + 33
                        else:
                            nama_y = y - 30
                            temp_y = y - 12

                        nama_y = min(max(nama_y, 0), img_h-1)
                        temp_y = min(max(temp_y, 0), img_h-1)
                        nama_x = min(max(0, x+5), img_w-1)
                        temp_x = nama_x

                        # Nama objek
                        cv2.putText(thermal_display, nama_objek, (nama_x, nama_y), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, nama_objek, (nama_x, nama_y), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)

                        # Temperature dengan format: XX.X°C/YY°C
                        text_temp = f"{max_temp:.1f}"
                        (text_width_temp, _), _ = cv2.getTextSize(text_temp, font_obj, font_scale_obj*0.8, thickness_obj)
                        text_threshold = f"/{obj_threshold}"
                        (text_width_threshold, _), _ = cv2.getTextSize(text_threshold, font_obj, font_scale_obj*0.8, thickness_obj)

                        # Background hitam untuk outline
                        cv2.putText(thermal_display, text_temp, (temp_x, temp_y), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, "o", (temp_x+text_width_temp+2, temp_y-7), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, "C", (temp_x+text_width_temp+14, temp_y), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, text_threshold, (temp_x+text_width_temp+24, temp_y), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, "o", (temp_x+text_width_temp+24+text_width_threshold+2, temp_y-7), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)
                        cv2.putText(thermal_display, "C", (temp_x+text_width_temp+24+text_width_threshold+14, temp_y), font_obj, font_scale_obj*0.8, (0,0,0), thickness_obj+2)

                        # Text putih di atas
                        cv2.putText(thermal_display, text_temp, (temp_x, temp_y), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)
                        cv2.putText(thermal_display, "o", (temp_x+text_width_temp+2, temp_y-7), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)
                        cv2.putText(thermal_display, "C", (temp_x+text_width_temp+14, temp_y), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)
                        cv2.putText(thermal_display, text_threshold, (temp_x+text_width_temp+24, temp_y), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)
                        cv2.putText(thermal_display, "o", (temp_x+text_width_temp+24+text_width_threshold+2, temp_y-7), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)
                        cv2.putText(thermal_display, "C", (temp_x+text_width_temp+24+text_width_threshold+14, temp_y), font_obj, font_scale_obj*0.8, (255,255,255), thickness_obj)

                    except Exception as e:
                        print(f"[DRAW BBOX ERROR] {e}")

                elif obj_type == 'LINE':
                    start_pt, end_pt = coords
                    color = (0, 0, 255) if max_temp >= obj_threshold else (80, 200, 120)
                    cv2.line(thermal_display, tuple(start_pt), tuple(end_pt), color, 2)

                    mid_x, mid_y = (start_pt[0] + end_pt[0]) // 2, (start_pt[1] + end_pt[1]) // 2

                    # Nama objek
                    cv2.putText(thermal_display, nama_objek, (mid_x+5, mid_y-10), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, nama_objek, (mid_x+5, mid_y-10), font_obj, font_scale_obj, (255,255,255), thickness_obj)

                    # Temperature dengan format lengkap
                    text_temp = f"{max_temp:.1f}"
                    (text_width_temp, _), _ = cv2.getTextSize(text_temp, font_obj, font_scale_obj, thickness_obj)
                    text_threshold = f"/{obj_threshold}"
                    (text_width_threshold, _), _ = cv2.getTextSize(text_threshold, font_obj, font_scale_obj, thickness_obj)

                    # Background hitam
                    cv2.putText(thermal_display, text_temp, (mid_x+5, mid_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "o", (mid_x+5+text_width_temp+2, mid_y+8), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "C", (mid_x+5+text_width_temp+14, mid_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, text_threshold, (mid_x+5+text_width_temp+24, mid_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "o", (mid_x+5+text_width_temp+24+text_width_threshold+2, mid_y+8), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "C", (mid_x+5+text_width_temp+24+text_width_threshold+14, mid_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)

                    # Text putih
                    cv2.putText(thermal_display, text_temp, (mid_x+5, mid_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "o", (mid_x+5+text_width_temp+2, mid_y+8), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "C", (mid_x+5+text_width_temp+14, mid_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, text_threshold, (mid_x+5+text_width_temp+24, mid_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "o", (mid_x+5+text_width_temp+24+text_width_threshold+2, mid_y+8), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "C", (mid_x+5+text_width_temp+24+text_width_threshold+14, mid_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)

                elif obj_type == 'POINT':
                    point_x, point_y = coords
                    color = (0, 0, 255) if max_temp >= obj_threshold else (80, 200, 120)
                    cv2.circle(thermal_display, (point_x, point_y), 5, color, -1)

                    # Nama objek
                    cv2.putText(thermal_display, nama_objek, (point_x+10, point_y-10), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, nama_objek, (point_x+10, point_y-10), font_obj, font_scale_obj, (255,255,255), thickness_obj)

                    # Temperature dengan format lengkap
                    text_temp = f"{max_temp:.1f}"
                    (text_width_temp, _), _ = cv2.getTextSize(text_temp, font_obj, font_scale_obj, thickness_obj)
                    text_threshold = f"/{obj_threshold}"
                    (text_width_threshold, _), _ = cv2.getTextSize(text_threshold, font_obj, font_scale_obj, thickness_obj)

                    # Background hitam
                    cv2.putText(thermal_display, text_temp, (point_x+10, point_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "o", (point_x+10+text_width_temp+2, point_y+8), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "C", (point_x+10+text_width_temp+14, point_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, text_threshold, (point_x+10+text_width_temp+24, point_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "o", (point_x+10+text_width_temp+24+text_width_threshold+2, point_y+8), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)
                    cv2.putText(thermal_display, "C", (point_x+10+text_width_temp+24+text_width_threshold+14, point_y+15), font_obj, font_scale_obj, (0,0,0), thickness_obj+2)

                    # Text putih
                    cv2.putText(thermal_display, text_temp, (point_x+10, point_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "o", (point_x+10+text_width_temp+2, point_y+8), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "C", (point_x+10+text_width_temp+14, point_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, text_threshold, (point_x+10+text_width_temp+24, point_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "o", (point_x+10+text_width_temp+24+text_width_threshold+2, point_y+8), font_obj, font_scale_obj, (255,255,255), thickness_obj)
                    cv2.putText(thermal_display, "C", (point_x+10+text_width_temp+24+text_width_threshold+14, point_y+15), font_obj, font_scale_obj, (255,255,255), thickness_obj)

                elif obj_type == 'POLYGON':
                    if len(coords) >= 3:
                        points = np.array(coords, dtype=np.int32)
                        color = (0, 0, 255) if max_temp >= obj_threshold else (80, 200, 120)
                        cv2.polylines(thermal_display, [points], True, color, 2)

                        # Hitung centroid untuk label
                        centroid_x = int(np.mean([p[0] for p in coords]))
                        centroid_y = int(np.mean([p[1] for p in coords]))

                        try:
                            img_h, img_w = thermal_display.shape[:2]
                            MIN_LABEL_MARGIN = 5

                            topmost_y = min([p[1] for p in coords])

                            label_y = max(0, topmost_y - 20)
                            label_x = min(max(0, centroid_x + 5), img_w - 1)

                            temp_y = min(label_y + 18, img_h - 1)
                            temp_x = label_x

                            # Nama objek
                            cv2.putText(thermal_display, f"{nama_objek}", (label_x, label_y), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, f"{nama_objek}", (label_x, label_y), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)

                            # Temperature dengan format lengkap
                            text_temp = f"{max_temp:.1f}"
                            (text_width_temp, _), _ = cv2.getTextSize(text_temp, font_obj, font_scale_obj, thickness_obj)
                            text_threshold = f"/{obj_threshold}"
                            (text_width_threshold, _), _ = cv2.getTextSize(text_threshold, font_obj, font_scale_obj, thickness_obj)

                            # Background hitam
                            cv2.putText(thermal_display, text_temp, (temp_x, temp_y), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, "o", (temp_x + text_width_temp + 2, temp_y - 7), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, "C", (temp_x + text_width_temp + 14, temp_y), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, text_threshold, (temp_x + text_width_temp + 24, temp_y), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, "o", (temp_x + text_width_temp + 24 + text_width_threshold + 2, temp_y - 7), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)
                            cv2.putText(thermal_display, "C", (temp_x + text_width_temp + 24 + text_width_threshold + 14, temp_y), font_obj, font_scale_obj, (0, 0, 0), thickness_obj + 2)

                            # Text putih
                            cv2.putText(thermal_display, text_temp, (temp_x, temp_y), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                            cv2.putText(thermal_display, "o", (temp_x + text_width_temp + 2, temp_y - 7), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                            cv2.putText(thermal_display, "C", (temp_x + text_width_temp + 14, temp_y), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                            cv2.putText(thermal_display, text_threshold, (temp_x + text_width_temp + 24, temp_y), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                            cv2.putText(thermal_display, "o", (temp_x + text_width_temp + 24 + text_width_threshold + 2, temp_y - 7), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                            cv2.putText(thermal_display, "C", (temp_x + text_width_temp + 24 + text_width_threshold + 14, temp_y), font_obj, font_scale_obj, (255, 255, 255), thickness_obj)
                        except Exception as e:
                            print(f"[DRAW POLYGON ERROR] {e}")

            # ========== STATUS OVERLAY ==========
            # Background processing indicator
            # cv2.putText(thermal_display, "BACKGROUND: ACTIVE", (10, 30),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

            # Overheat warning
            if self.confirmed_overheat_states:
                cv2.putText(thermal_display, "!!! OVERHEAT DETECTED !!!", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

            # Cursor mode
            if cursor_temp_enabled and self.cursor_pos:
                cursor_x, cursor_y = self.cursor_pos
                if 0 <= cursor_x < temp_frame_resized.shape[1] and 0 <= cursor_y < temp_frame_resized.shape[0]:
                    self.cursor_temp = float(temp_frame_resized[cursor_y, cursor_x])
                    cv2.line(thermal_display, (cursor_x-10, cursor_y), (cursor_x+10, cursor_y), (0, 255, 255), 1)
                    cv2.line(thermal_display, (cursor_x, cursor_y-10), (cursor_x, cursor_y+10), (0, 255, 255), 1)
                    cv2.circle(thermal_display, (cursor_x, cursor_y), 3, (0, 255, 255), -1)

                cv2.putText(thermal_display, "Cursor Mode: ON", (10, 110),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)

            # ========== COOLDOWN INFORMATION ==========
            # Tampilkan informasi cooldown untuk objek yang overheat (seperti di process_frame)
            if self.confirmed_overheat_states:  # <-- PERUBAHAN 1: Gunakan status persisten
                y_offset = 130
                # Iterasi melalui objek yang statusnya overheat secara persisten
                for i, obj in enumerate(self.confirmed_overheat_states.values()): # <-- PERUBAHAN 2
                    obj_name = obj['name']
                    last_notif = self.object_last_notification.get(obj_name, 0)
                    if last_notif > 0:
                        time_since = current_time - last_notif
                        remaining = max(0, self.object_notification_cooldown - time_since)
                        if remaining > 0:
                            cv2.putText(thermal_display, f"{obj_name}: Cooldown {remaining:.0f}s",
                                        (450, y_offset + i*20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)


            self.thermal_frame = thermal_display
            return thermal_display

    def _process_frame_complete(self):
        """Fallback: Complete processing jika background thread tidak aktif"""
        # Ini adalah kode asli process_frame() untuk backward compatibility
        return self.thermal_frame


    # ========== PERBAIKAN: Method untuk mendapatkan notification log ==========
    def get_notification_log(self):
        """Dapatkan log notifikasi untuk debugging"""
        return self.notification_log.copy()

    # ========== PERBAIKAN: Method untuk reset notification tracking ==========
    def reset_notification_tracking(self):
        """Reset tracking notifikasi (untuk testing/debugging)"""
        self.object_last_notification.clear()
        self.notification_log.clear()
        print("✅ Notification tracking direset")

    def _calculate_fps_loop(self):
        """Thread terpisah untuk menghitung processing FPS setiap 2 detik."""
        print("🚀 FPS calculation thread started.")
        while self.running:
            time.sleep(2) # Hitung setiap 2 detik

            # Hitung selisih waktu
            elapsed_time = time.time() - self.fps_start_time
            if elapsed_time > 0:
                # Kalkulasi FPS
                self.processing_fps = self.frame_counter / elapsed_time

            # Reset counter dan timer
            self.frame_counter = 0
            self.fps_start_time = time.time()

# Inisialisasi ESP32 monitor dengan config yang dimuat
thermal_monitor = ESP32ThermalMonitor(esp32_host=ESP32_HOST, esp32_port=ESP32_PORT)

def generate_frames():
    """Generator untuk streaming video"""
    while True:
        if thermal_monitor.running:
            frame = thermal_monitor.process_frame()
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            # Kirim frame kosong jika kamera tidak aktif
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank_frame, "ESP32 Camera Stopped", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', blank_frame)
            if ret:
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')


@app.route('/')
def index():
    """Halaman utama"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Streaming video feed"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/start_camera', methods=['POST'])
def start_camera():
    """API untuk mulai ESP32 thermal camera"""
    if thermal_monitor.start_camera():
        return jsonify({'status': 'success', 'message': 'ESP32 thermal camera started'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to connect to ESP32'})

@app.route('/api/stop_camera', methods=['POST'])
def stop_camera():
    """API untuk hentikan ESP32 thermal camera"""
    thermal_monitor.stop_camera()
    return jsonify({'status': 'success', 'message': 'ESP32 thermal camera stopped'})

@app.route('/api/toggle_background_processing', methods=['POST'])
def toggle_background_processing():
    """API untuk toggle background processing"""
    try:
        data = request.json
        enable = data.get('enable', not thermal_monitor.enable_background_processing)

        thermal_monitor.enable_background_processing = enable

        if enable and thermal_monitor.running and not thermal_monitor.background_running:
            thermal_monitor.start_background_processing()
            message = "Background processing enabled - sistem akan terus berjalan tanpa browser"
        elif not enable and thermal_monitor.background_running:
            thermal_monitor.stop_background_processing()
            message = "Background processing disabled - hanya aktif saat ada yang membuka browser"
        else:
            message = f"Background processing {'enabled' if enable else 'disabled'} (tidak ada perubahan status)"

        return jsonify({
            'status': 'success',
            'background_enabled': thermal_monitor.enable_background_processing,
            'background_running': thermal_monitor.background_running,
            'message': message
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_background_status', methods=['GET'])
def get_background_status():
    """API untuk mendapatkan status background processing"""
    return jsonify({
        'background_enabled': thermal_monitor.enable_background_processing,
        'background_running': thermal_monitor.background_running,
        'camera_running': thermal_monitor.running,
        'monitoring_objects': len(monitoring_objects),
        'last_process_time': thermal_monitor.last_process_time,
        'status': 'success'
    })

@app.route('/api/set_esp32_config', methods=['POST'])
def set_esp32_config():
    """Set konfigurasi ESP32 host dan port dengan persistensi"""
    global ESP32_HOST, ESP32_PORT

    try:
        data = request.json
        new_host = data.get('host', ESP32_HOST)
        new_port = data.get('port', ESP32_PORT)

        # Validasi input
        if not new_host or not new_host.strip():
            return jsonify({'status': 'error', 'message': 'Host cannot be empty'})

        try:
            new_port = int(new_port)
            if new_port < 1 or new_port > 65535:
                raise ValueError("Port out of range")
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Port must be a valid number between 1-65535'})

        # Update global variables
        ESP32_HOST = new_host.strip()
        ESP32_PORT = new_port

        # Update thermal monitor instance
        thermal_monitor.esp32_host = ESP32_HOST
        thermal_monitor.esp32_port = ESP32_PORT

        # Save to file untuk persistensi
        if save_esp32_config():
            return jsonify({
                'status': 'success',
                'message': f'ESP32 config saved: {ESP32_HOST}:{ESP32_PORT}',
                'host': ESP32_HOST,
                'port': ESP32_PORT
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': f'ESP32 config updated but failed to save: {ESP32_HOST}:{ESP32_PORT}',
                'host': ESP32_HOST,
                'port': ESP32_PORT
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_esp32_config', methods=['GET'])
def get_esp32_config():
    """Get current ESP32 configuration"""
    return jsonify({
        'host': ESP32_HOST,
        'port': ESP32_PORT,
        'status': 'success'
    })

@app.route('/api/get_esp32_status', methods=['GET'])
def get_esp32_status():
    """Get status koneksi ESP32"""
    connected = thermal_monitor.socket is not None and thermal_monitor.running
    return jsonify({
        'esp32_connected': connected,
        'esp32_host': ESP32_HOST,  # Gunakan global variable
        'esp32_port': ESP32_PORT,  # Gunakan global variable
        'status': 'Connected' if connected else 'Disconnected'
    })

@app.route('/api/add_object', methods=['POST'])
def add_object():
    """API untuk menambah objek monitoring"""
    global area_counter
    try:
        data = request.json
        print(f"Received object data: {data}")

        obj_data = {
            'name': data.get('name', f"{data['type']} {area_counter}"),
            'type': data['type'],
            'coords': data['coords'],
            'threshold': data.get('threshold', default_threshold_value),  # Default 50°C untuk thermal real
            'temp': 0
        }

        monitoring_objects.append(obj_data)
        area_counter += 1

        # ========== TAMBAHAN: Auto-save setelah menambah object ==========
        save_monitoring_objects()

        print(f"Object added: {obj_data}")
        return jsonify({'status': 'success', 'message': 'Object added'})
    except Exception as e:
        print(f"Error adding object: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/update_object_threshold', methods=['POST'])
def update_object_threshold():
    """API untuk update threshold objek tertentu"""
    try:
        data = request.json
        object_name = data.get('name')
        new_threshold = int(data.get('threshold'))

        # Cari dan update objek
        for obj in monitoring_objects:
            if obj['name'] == object_name:
                obj['threshold'] = new_threshold

                # ========== TAMBAHAN: Auto-save setelah update threshold ==========
                save_monitoring_objects()

                return jsonify({
                    'status': 'success',
                    'message': f'Threshold untuk {object_name} berhasil diupdate ke {new_threshold}°C'
                })

        return jsonify({'status': 'error', 'message': 'Objek tidak ditemukan'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_objects', methods=['GET'])
def get_objects():
    """API untuk mendapatkan daftar objek"""
    return jsonify({'objects': monitoring_objects})

@app.route('/api/clear_objects', methods=['POST'])
def clear_objects():
    """API untuk menghapus semua objek"""
    global area_counter

    monitoring_objects.clear()
    area_counter = 1

    thermal_monitor.reset_notification_tracking()

    save_monitoring_objects()

    return jsonify({'status': 'success', 'message': 'All objects cleared and notification tracking reset'})

@app.route('/api/delete_object', methods=['POST'])
def delete_object():
    """API untuk menghapus objek tertentu"""
    try:
        data = request.json
        object_name = data.get('name')

        # Cari dan hapus objek
        for i, obj in enumerate(monitoring_objects):
            if obj['name'] == object_name:
                monitoring_objects.pop(i)

                # ========== PERBAIKAN: Hapus tracking notifikasi untuk objek yang dihapus ==========
                if object_name in thermal_monitor.object_last_notification:
                    del thermal_monitor.object_last_notification[object_name]
                    print(f"Notification tracking untuk {object_name} dihapus")

                # ========== TAMBAHAN: Auto-save setelah delete object ==========
                save_monitoring_objects()

                return jsonify({
                    'status': 'success',
                    'message': f'Objek {object_name} berhasil dihapus'
                })

        return jsonify({'status': 'error', 'message': 'Objek tidak ditemukan'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_status', methods=['GET'])
def get_status():
    """API untuk mendapatkan status sistem"""
    wa_bot_status = test_wwebjs_bot_connection()
    esp32_status = thermal_monitor.socket is not None and thermal_monitor.running
    influx_status = influx_client is not None and influx_write_api is not None

    # Cari nama colormap saat ini
    current_colormap_name = 'INFERNO'
    for name, value in AVAILABLE_COLORMAPS.items():
        if value == current_colormap:
            current_colormap_name = name
            break

    return jsonify({
        'camera_active': thermal_monitor.running,
        'max_temp': thermal_monitor.max_temp_global,
        'default_threshold': default_threshold_value,
        'objects_count': len(monitoring_objects),
        'overheat_objects': thermal_monitor.overheat_objects,
        'persistent_overheat_list': list(thermal_monitor.confirmed_overheat_states.values()),
        'cursor_enabled': cursor_temp_enabled,
        'cursor_temp': thermal_monitor.cursor_temp if cursor_temp_enabled else 0,
        'whatsapp_bot_status': 'Connected' if wa_bot_status else 'Disconnected',
        'esp32_status': 'Connected' if esp32_status else 'Disconnected',
        'influxdb_status': 'Connected' if influx_status else 'Disconnected',
        'esp32_host': ESP32_HOST,      # Gunakan global variable
        'esp32_port': ESP32_PORT,      # Gunakan global variable
        'sensor_type': 'ESP32 Thermal Camera',  # Update info sensor
        # ========== PERBAIKAN: Tambahan info notifikasi ==========
        'notification_cooldown': thermal_monitor.object_notification_cooldown,
        'active_notifications': len(thermal_monitor.object_last_notification),
        # ========== TAMBAHAN: Info persistensi ==========
        'objects_file_exists': os.path.exists(MONITORING_OBJECTS_FILE),
        'objects_file_path': MONITORING_OBJECTS_FILE,
        # ========== TAMBAHAN: Mirror status ==========
        'mirror_enabled': mirror_enabled,
        # ========== TAMBAHAN: Colormap status ==========
        'current_colormap': current_colormap_name,
        'available_colormaps': list(AVAILABLE_COLORMAPS.keys()),
        'processing_fps': round(thermal_monitor.processing_fps, 1),
        # ========== SMART LOGGING: Info interval logging ==========
        'logging_intervals': {
            'normal': thermal_monitor.normal_log_interval,
            'alert': thermal_monitor.alert_log_interval
        },
        'last_log_time': thermal_monitor.last_log_time
    })

@app.route('/api/set_default_threshold', methods=['POST'])
def set_default_threshold():
    """API untuk mengatur default threshold"""
    global default_threshold_value
    data = request.json
    default_threshold_value = int(data['threshold'])

    # ========== TAMBAHAN: Save setelah update default threshold ==========
    save_monitoring_objects()

    return jsonify({'status': 'success', 'message': f'Default threshold set to {default_threshold_value}°C'})

@app.route('/api/set_cursor_pos', methods=['POST'])
def set_cursor_pos():
    """API untuk update posisi cursor"""
    global cursor_temp_enabled
    try:
        data = request.json
        x = data.get('x', 0)
        y = data.get('y', 0)

        if cursor_temp_enabled:
            thermal_monitor.cursor_pos = (x, y)
            return jsonify({
                'status': 'success',
                'cursor_temp': thermal_monitor.cursor_temp,
                'position': [x, y]
            })
        else:
            return jsonify({'status': 'disabled'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/toggle_cursor', methods=['POST'])
def toggle_cursor():
    """API untuk toggle cursor mode"""
    global cursor_temp_enabled
    cursor_temp_enabled = not cursor_temp_enabled

    if not cursor_temp_enabled:
        thermal_monitor.cursor_pos = None
        thermal_monitor.cursor_temp = 0

    return jsonify({
        'status': 'success',
        'cursor_enabled': cursor_temp_enabled,
        'message': f'Cursor mode {"enabled" if cursor_temp_enabled else "disabled"}'
    })

@app.route('/api/get_cursor_status', methods=['GET'])
def get_cursor_status():
    """API untuk mendapatkan status cursor"""
    return jsonify({
        'cursor_enabled': cursor_temp_enabled,
        'cursor_temp': thermal_monitor.cursor_temp if cursor_temp_enabled else 0,
        'cursor_pos': thermal_monitor.cursor_pos if cursor_temp_enabled else None
    })

@app.route('/api/test_whatsapp', methods=['POST'])
def test_whatsapp():
    """API untuk test kirim WhatsApp"""
    data = request.json
    nomor = data.get('nomor')
    group_id = data.get('group_id')

    if not nomor and not group_id:
        return jsonify({'status': 'error', 'message': 'Nomor atau Group ID diperlukan'})

    recipients = {
        'personal': [nomor] if nomor else [],
        'groups': [group_id] if group_id else []
    }
    test_message = (
        f"✅ *PESAN TES BERHASIL*\n\n"
        f"Sistem Bot Monitoring Thermal berjalan dengan baik.\n"
        f"Waktu: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # ==================== PERBAIKAN DI SINI ====================
    screenshot_path = None
    # Cek apakah kamera berjalan dan sudah ada frame yang bisa diambil
    if thermal_monitor.running and thermal_monitor.thermal_frame is not None:
        try:
            # Pastikan direktori ada
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            # Buat nama file unik untuk screenshot tes
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"test_screenshot_{ts}.jpg"
            screenshot_path = os.path.join(SCREENSHOT_DIR, filename)

            # Simpan frame saat ini sebagai gambar
            cv2.imwrite(screenshot_path, thermal_monitor.thermal_frame)
            print(f"✅ Test screenshot saved: {screenshot_path}")

            # Tambahkan info screenshot ke pesan
            test_message += "\n\n_Screenshot thermal terlampir._"

        except Exception as e:
            print(f"❌ Error saat membuat screenshot tes: {e}")
            screenshot_path = None # Set kembali ke None jika gagal
    else:
        print("Kamera tidak aktif, pesan tes akan dikirim tanpa gambar.")
    # ==================== AKHIR PERBAIKAN ====================

    # Memanggil fungsi notifikasi yang sudah benar
    if kirim_notifikasi_whatsapp(recipients, test_message, screenshot_path):
        target = nomor or group_id
        return jsonify({'status': 'success', 'message': f'Pesan tes berhasil dikirim ke {target}'})
    else:
        return jsonify({'status': 'error', 'message': 'Gagal mengirim pesan tes. Pastikan API Bot berjalan.'})

@app.route('/api/check_whatsapp_bot', methods=['GET'])
def check_whatsapp_bot():
    status = test_wwebjs_bot_connection()
    return jsonify({'whatsapp_bot_connected': status, 'message': 'Connected' if status else 'Disconnected'})

@app.route('/api/get_whatsapp_bot_groups', methods=['GET'])
def get_whatsapp_bot_groups_api():
    groups = get_wwebjs_bot_groups()
    return jsonify({'groups': groups, 'count': len(groups)})

# ========== PERBAIKAN: API tambahan untuk debugging notifikasi ==========
@app.route('/api/get_notification_log', methods=['GET'])
def get_notification_log():
    """API untuk mendapatkan log notifikasi (debugging)"""
    return jsonify({
        'notification_log': thermal_monitor.get_notification_log(),
        'cooldown_period': thermal_monitor.object_notification_cooldown,
        'active_tracking': thermal_monitor.object_last_notification
    })

@app.route('/api/reset_notification_tracking', methods=['POST'])
def reset_notification_tracking():
    """API untuk reset tracking notifikasi (debugging/testing)"""
    thermal_monitor.reset_notification_tracking()
    return jsonify({'status': 'success', 'message': 'Notification tracking direset'})

@app.route('/api/set_notification_cooldown', methods=['POST'])
def set_notification_cooldown():
    """API untuk mengatur cooldown period notifikasi"""
    try:
        data = request.json
        new_cooldown = int(data.get('cooldown', 300))

        if new_cooldown < 30:
            return jsonify({'status': 'error', 'message': 'Cooldown minimum 30 detik'})

        thermal_monitor.object_notification_cooldown = new_cooldown
        return jsonify({
            'status': 'success',
            'message': f'Notification cooldown diubah ke {new_cooldown} detik'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ========== SMART LOGGING: API untuk mengatur interval logging ==========
@app.route('/api/set_logging_intervals', methods=['POST'])
def set_logging_intervals():
    """API untuk mengatur interval logging"""
    try:
        data = request.json
        normal_interval = int(data.get('normal', thermal_monitor.normal_log_interval))
        alert_interval = int(data.get('alert', thermal_monitor.alert_log_interval))

        # Validasi minimum interval
        if normal_interval < 10 or alert_interval < 5:
            return jsonify({'status': 'error', 'message': 'Interval terlalu kecil! Min: normal=10s, alert=5s'})

        # Update interval
        thermal_monitor.normal_log_interval = normal_interval
        thermal_monitor.alert_log_interval = alert_interval

        return jsonify({
            'status': 'success',
            'message': f'Logging intervals updated: normal={normal_interval}s, alert={alert_interval}s',
            'intervals': {
                'normal': normal_interval,
                'alert': alert_interval
            }
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_logging_stats', methods=['GET'])
def get_logging_stats():
    """API untuk mendapatkan statistik logging"""
    try:
        # Hitung ukuran file CSV
        csv_size = 0
        csv_lines = 0
        if os.path.exists(csv_filename):
            csv_size = os.path.getsize(csv_filename)
            with open(csv_filename, 'r') as f:
                csv_lines = sum(1 for _ in f) - 1  # minus header

        # Estimasi write rate berdasarkan interval saat ini
        if thermal_monitor.overheat_objects:
            current_interval = thermal_monitor.alert_log_interval
            mode = "ALERT"
        else:
            current_interval = thermal_monitor.normal_log_interval
            mode = "NORMAL"

        writes_per_day = int(86400 / current_interval) * len(monitoring_objects)

        return jsonify({
            'csv_file_size_bytes': csv_size,
            'csv_file_size_mb': round(csv_size / (1024*1024), 2),
            'csv_total_records': csv_lines,
            'current_logging_mode': mode,
            'current_interval': current_interval,
            'estimated_writes_per_day': writes_per_day,
            'monitoring_objects_count': len(monitoring_objects),
            'last_log_time_ago': int(time.time() - thermal_monitor.last_log_time) if thermal_monitor.last_log_time > 0 else 0,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ========== TAMBAHAN: Mirror/flip video stream API ==========
@app.route('/api/toggle_mirror', methods=['POST'])
def toggle_mirror():
    """API untuk toggle mirror/flip video stream"""
    global mirror_enabled
    mirror_enabled = not mirror_enabled

    return jsonify({
        'status': 'success',
        'mirror_enabled': mirror_enabled,
        'message': f'Mirror mode {"enabled" if mirror_enabled else "disabled"}'
    })

@app.route('/api/get_mirror_status', methods=['GET'])
def get_mirror_status():
    """API untuk mendapatkan status mirror"""
    return jsonify({
        'mirror_enabled': mirror_enabled,
        'status': 'success'
    })

# ========== TAMBAHAN: Colormap API endpoints ==========
@app.route('/api/set_colormap', methods=['POST'])
def set_colormap():
    """API untuk mengatur colormap"""
    global current_colormap

    try:
        data = request.json
        colormap_name = data.get('colormap', 'INFERNO').upper()

        if colormap_name not in AVAILABLE_COLORMAPS:
            return jsonify({'status': 'error', 'message': f'Invalid colormap: {colormap_name}'})

        current_colormap = AVAILABLE_COLORMAPS[colormap_name]

        # Save to file untuk persistensi
        if save_colormap_config():
            return jsonify({
                'status': 'success',
                'message': f'Colormap changed to {colormap_name}',
                'colormap': colormap_name
            })
        else:
            return jsonify({
                'status': 'warning',
                'message': f'Colormap updated but failed to save: {colormap_name}',
                'colormap': colormap_name
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/get_colormap', methods=['GET'])
def get_colormap():
    """API untuk mendapatkan colormap saat ini"""
    # Cari nama colormap dari value
    colormap_name = 'INFERNO'
    for name, value in AVAILABLE_COLORMAPS.items():
        if value == current_colormap:
            colormap_name = name
            break

    return jsonify({
        'current_colormap': colormap_name,
        'available_colormaps': list(AVAILABLE_COLORMAPS.keys()),
        'status': 'success'
    })

# ========== TAMBAHAN: Simple load API untuk startup ==========
@app.route('/api/load_objects', methods=['POST'])
def load_objects():
    """API untuk load monitoring objects dari file saat startup"""
    try:
        if load_monitoring_objects():
            return jsonify({
                'status': 'success',
                'message': f'Berhasil load {len(monitoring_objects)} objects',
                'objects_count': len(monitoring_objects)
            })
        else:
            return jsonify({'status': 'success', 'message': 'Tidak ada file tersimpan sebelumnya', 'objects_count': 0})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/manage_contacts', methods=['GET', 'POST'])
def manage_contacts():
    """API untuk kelola kontak WhatsApp"""
    if request.method == 'GET':
        try:
            if os.path.exists(CSV_NOMOR_WA):
                df = pd.read_csv(CSV_NOMOR_WA)
                contacts = df.to_dict('records')
            else:
                contacts = []
            return jsonify({'contacts': contacts})
        except Exception as e:
            return jsonify({'contacts': [], 'error': str(e)})

    elif request.method == 'POST':
        try:
            data = request.json
            action = data.get('action')

            if action == 'add':
                nomor = data.get('nomor', '').strip()
                nama = data.get('nama', 'Tanpa Nama').strip()

                if not nomor or not nomor.startswith('62'):
                    return jsonify({'status': 'error', 'message': 'Nomor harus dimulai dengan 62'})

                # Buat atau update file CSV
                if os.path.exists(CSV_NOMOR_WA):
                    df = pd.read_csv(CSV_NOMOR_WA)
                else:
                    df = pd.DataFrame(columns=['Nomor_WhatsApp', 'Nama'])

                # Cek apakah nomor sudah ada
                if len(df) > 0 and nomor in df['Nomor_WhatsApp'].astype(str).values:
                    return jsonify({'status': 'error', 'message': 'Nomor sudah terdaftar!'})

                # Tambah nomor baru
                new_row = pd.DataFrame({'Nomor_WhatsApp': [nomor], 'Nama': [nama]})
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(CSV_NOMOR_WA, index=False)

                return jsonify({'status': 'success', 'message': f'Nomor {nomor} berhasil ditambahkan'})

            elif action == 'delete':
                nomor = data.get('nomor', '').strip()

                if os.path.exists(CSV_NOMOR_WA):
                    df = pd.read_csv(CSV_NOMOR_WA)
                    df = df[df['Nomor_WhatsApp'].astype(str) != nomor]
                    df.to_csv(CSV_NOMOR_WA, index=False)
                    return jsonify({'status': 'success', 'message': f'Nomor {nomor} berhasil dihapus'})
                else:
                    return jsonify({'status': 'error', 'message': 'File kontak tidak ditemukan'})

        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/manage_groups', methods=['GET', 'POST'])
def manage_groups():
    """API untuk kelola grup WhatsApp"""
    if request.method == 'GET':
        try:
            if os.path.exists(CSV_GROUP_WA):
                df = pd.read_csv(CSV_GROUP_WA)
                groups = df.to_dict('records')
            else:
                groups = []
            return jsonify({'groups': groups})
        except Exception as e:
            return jsonify({'groups': [], 'error': str(e)})

    elif request.method == 'POST':
        try:
            data = request.json
            action = data.get('action')

            if action == 'add':
                group_id = data.get('group_id', '').strip()
                nama = data.get('nama', 'Tanpa Nama').strip()

                if not group_id:
                    return jsonify({'status': 'error', 'message': 'Group ID tidak boleh kosong'})

                # Pastikan format group_id benar
                if not group_id.endswith('@g.us'):
                    group_id += '@g.us'

                # Buat atau update file CSV
                if os.path.exists(CSV_GROUP_WA):
                    df = pd.read_csv(CSV_GROUP_WA)
                else:
                    df = pd.DataFrame(columns=['Group_ID', 'Nama'])

                # Cek apakah group_id sudah ada
                if len(df) > 0 and group_id in df['Group_ID'].astype(str).values:
                    return jsonify({'status': 'error', 'message': 'Group ID sudah terdaftar!'})

                # Tambah grup baru
                new_row = pd.DataFrame({'Group_ID': [group_id], 'Nama': [nama]})
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv(CSV_GROUP_WA, index=False)

                return jsonify({'status': 'success', 'message': f'Grup {nama} berhasil ditambahkan'})

            elif action == 'delete':
                group_id = data.get('group_id', '').strip()

                if os.path.exists(CSV_GROUP_WA):
                    df = pd.read_csv(CSV_GROUP_WA)
                    df = df[df['Group_ID'].astype(str) != group_id]
                    df.to_csv(CSV_GROUP_WA, index=False)
                    return jsonify({'status': 'success', 'message': f'Grup berhasil dihapus'})
                else:
                    return jsonify({'status': 'error', 'message': 'File grup tidak ditemukan'})

        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

# ========== TAMBAHAN: Fungsi untuk Auto-Restart Kamera ==========
def auto_restart_camera():
    """
    Fungsi yang berjalan di background untuk me-restart kamera secara periodik.
    """
    print(f"🔄 Auto-restart kamera diaktifkan dengan interval {AUTO_RESTART_INTERVAL_MINUTES} menit.")

    # Konversi menit ke detik
    wait_seconds = AUTO_RESTART_INTERVAL_MINUTES * 60

    while True:
        # Tunggu sesuai interval yang ditentukan
        time.sleep(wait_seconds)

        # Lakukan restart hanya jika kamera sedang berjalan
        if thermal_monitor.running:
            print(f"\n[AUTO-RESTART] Memulai siklus restart terjadwal ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})...")

            try:
                # 1. Stop kamera
                print("[AUTO-RESTART] Menghentikan kamera...")
                thermal_monitor.stop_camera()

                # 2. Tunggu 3 detik
                print("[AUTO-RESTART] Menunggu 3 detik...")
                time.sleep(3)

                # 3. Start kamera lagi
                print("[AUTO-RESTART] Menjalankan kembali kamera...")
                if thermal_monitor.start_camera():
                    print("✅ [AUTO-RESTART] Kamera berhasil dijalankan kembali.")
                else:
                    print("❌ [AUTO-RESTART] Gagal menjalankan kembali kamera. Akan dicoba lagi pada siklus berikutnya.")

            except Exception as e:
                print(f"❌ [AUTO-RESTART] Terjadi error saat siklus restart: {e}")

            print(f"[AUTO-RESTART] Siklus selesai. Menunggu {AUTO_RESTART_INTERVAL_MINUTES} menit untuk siklus berikutnya.\n")
        else:
            # Jika kamera tidak berjalan, cukup cetak status dan tunggu lagi
            print(f"[AUTO-RESTART] Melewatkan siklus karena kamera sedang tidak aktif.")

# TAMBAHAN: SocketIO untuk latency
@socketio.on('ping_from_client')
def handle_ping():
    """Menangani ping dari client dan langsung membalas dengan pong."""
    emit('pong_from_server')

if __name__ == '__main__':
    # ========== Load ESP32 config saat startup ==========
    print("=== ESP32 Thermal Monitoring Web Server ===")
    print("Loading saved configurations...")

    # Load ESP32 config
    load_esp32_config()

    # Load colormap config
    load_colormap_config()

    # Update thermal monitor dengan config yang dimuat
    thermal_monitor.esp32_host = ESP32_HOST
    thermal_monitor.esp32_port = ESP32_PORT

    # Load monitoring objects
    load_monitoring_objects()

    # Pastikan direktori ada
    os.makedirs(os.path.dirname(CSV_NOMOR_WA), exist_ok=True)
    os.makedirs(os.path.dirname(CSV_GROUP_WA), exist_ok=True)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # ========== Pastikan direktori untuk config files ada ==========
    os.makedirs(os.path.dirname(MONITORING_OBJECTS_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(ESP32_CONFIG_FILE), exist_ok=True)

    # Buat file CSV jika belum ada
    if not os.path.exists(CSV_NOMOR_WA):
        df_empty = pd.DataFrame(columns=['Nomor_WhatsApp', 'Nama'])
        df_empty.to_csv(CSV_NOMOR_WA, index=False)

    if not os.path.exists(CSV_GROUP_WA):
        df_empty = pd.DataFrame(columns=['Group_ID', 'Nama'])
        df_empty.to_csv(CSV_GROUP_WA, index=False)

    # Buat file log CSV jika belum ada
    if not os.path.exists(csv_filename):
        with open(csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Object_Name", "Type", "Max_Suhu", "Threshold", "Status"])

    print(f"ESP32 Config: {ESP32_HOST}:{ESP32_PORT}")

    # Display current colormap
    current_colormap_name = 'INFERNO'
    for name, value in AVAILABLE_COLORMAPS.items():
        if value == current_colormap:
            current_colormap_name = name
            break
    print(f"Current Colormap: {current_colormap_name}")

    # ========== SMART LOGGING: Display logging intervals ==========
    print(f"Logging Intervals:")
    print(f"  Normal: {thermal_monitor.normal_log_interval}s")
    print(f"  Alert: {thermal_monitor.alert_log_interval}s")

    print("Web Access: http://[IP_ANDA]:5000")

    # Test connections
    if test_wwebjs_bot_connection():
            print("WhatsApp Bot API: Connected")
            groups = get_wwebjs_bot_groups()
            print(f"Available Groups: {len(groups)} found")
    else:
        print("WhatsApp Bot API: Not Connected - Please start the Node.js bot first")


    if influx_write_api:
        print("InfluxDB: Connected")
    else:
        print("InfluxDB: Not Connected - Check configuration and server status")

    if AUTO_START_ON_BOOT:
            print("Auto-start diaktifkan. Mencoba memulai kamera dalam 5 detik...")
            time.sleep(5) # Memberi jeda agar service lain siap
            thermal_monitor.start_camera()

    # ========== TAMBAHAN: Mulai Thread Auto-Restart Kamera ==========
    if ENABLE_AUTO_RESTART:
        restart_thread = threading.Thread(target=auto_restart_camera, daemon=True)
        restart_thread.start()

    print("=============================================================")

    # Jalankan server
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
