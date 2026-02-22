#!/usr/bin/env python3
"""
Lokaler Proxy-Server für Meshtastic Wetterdaten
Umgeht CORS-Beschränkungen durch lokalen Server
Mit 5-Minuten-Cache für API-Anfragen
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
from math import radians, sin, cos, sqrt, atan2
from time import time

# Cache-Speicher (global für alle Requests)
cache = {
    'data': None,
    'timestamp': 0
}

CACHE_DURATION = 300  # 5 Minuten in Sekunden

def calculate_distance(lat1, lon1, lat2, lon2):
    """Berechnet die Distanz zwischen zwei Koordinaten in Kilometern."""
    earth_radius = 6371
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return earth_radius * c

class WeatherProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if path == '/':
            self.serve_html()
        elif path == '/nodes':
            self.proxy_nodes()
        elif path == '/api':
            self.handle_api(query_params)
        else:
            self.send_error(404)

    def send_json(self, payload, status=200, extra_headers=None):
        """Sendet eine JSON-Antwort mit CORS-Headern."""
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def get_nodes_data(self):
        """Lädt Node-Daten mit Cache und liefert (bytes, cache_status) zurück."""
        global cache

        current_time = time()
        cache_age = current_time - cache['timestamp']
        cache_is_valid = cache['data'] is not None and cache_age < CACHE_DURATION

        if cache_is_valid:
            print(f"✓ Cache verwendet (noch {int(CACHE_DURATION - cache_age)}s gültig)")
            return cache['data'], 'HIT'

        print("↻ Neue Daten von API abrufen...")
        with urllib.request.urlopen('https://api.bolte.lol/nodes') as response:
            data = response.read()
        cache['data'] = data
        cache['timestamp'] = current_time
        print(f"✓ Daten gecached für {CACHE_DURATION}s")
        return data, 'MISS'

    def fetch_openmeteo_current(self, lat, lon):
        """Lädt aktuelle Open-Meteo Daten für die angegebenen Koordinaten."""
        url = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,surface_pressure"
        )
        with urllib.request.urlopen(url) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return payload.get('current', {})

    def parse_coordinate(self, query_params, primary, fallback=None):
        """Parst einen Koordinaten-Parameter als float."""
        value = query_params.get(primary, [None])[0]
        if value is None and fallback:
            value = query_params.get(fallback, [None])[0]
        if value is None:
            return None
        return float(value)

    def find_nearest_node(self, user_lat, user_lon, nodes):
        """Findet die nächste Node mit gültigen Koordinaten."""
        nearest = None
        min_distance = float('inf')

        for node in nodes:
            node_lat = node.get('latitude')
            node_lon = node.get('longitude')
            if node_lat is None or node_lon is None:
                continue

            distance = calculate_distance(user_lat, user_lon, float(node_lat), float(node_lon))
            if distance < min_distance:
                min_distance = distance
                nearest = node

        return nearest, min_distance

    def find_best_matching_node(self, user_lat, user_lon, nodes, openmeteo_current):
        """
        Gleiche Logik wie auf der Hauptseite:
        - Kandidaten mit gültigen Wetterdaten
        - Wenn möglich Temperatur-Match zu Open-Meteo (<= 2°C) und dann kürzeste Distanz
        - Sonst Fallback: kleinste Temperaturabweichung, dann Distanz
        """
        ref_temp = openmeteo_current.get('temperature_2m')
        candidates = []
        for node in nodes:
            node_lat = node.get('latitude')
            node_lon = node.get('longitude')
            node_temp = node.get('temperature')
            node_humidity = node.get('relative_humidity')
            node_pressure = node.get('barometric_pressure')

            if (
                node_lat is None or node_lon is None or
                node_temp is None or node_humidity is None or node_pressure is None
            ):
                continue

            distance_km = calculate_distance(user_lat, user_lon, float(node_lat), float(node_lon))
            temp_diff = abs(float(node_temp) - float(ref_temp)) if ref_temp is not None else 0.0

            candidates.append({
                'node': node,
                'distance_km': distance_km,
                'temp_diff': temp_diff,
            })

        if not candidates:
            return None, None

        if ref_temp is None:
            best = sorted(candidates, key=lambda c: c['distance_km'])[0]
            return best['node'], best

        # Wie im Frontend: bei passenden Temperaturen die nächste Node wählen.
        matching = [c for c in candidates if c['temp_diff'] <= 2]
        if matching:
            best = sorted(matching, key=lambda c: c['distance_km'])[0]
            return best['node'], best

        # Fallback wie im Frontend: kleinste Temperaturabweichung, dann Distanz.
        best = sorted(candidates, key=lambda c: (c['temp_diff'], c['distance_km']))[0]
        return best['node'], best

    def handle_api(self, query_params):
        """API: /api?lat=52.1&long=10.1 -> nächste Node + Open-Meteo Vergleich."""
        try:
            user_lat = self.parse_coordinate(query_params, 'lat')
            user_lon = self.parse_coordinate(query_params, 'long', fallback='lon')
        except ValueError:
            self.send_json(
                {'error': 'Ungültige Koordinaten. Bitte numerische Werte für lat und long verwenden.'},
                status=400
            )
            return

        if user_lat is None or user_lon is None:
            self.send_json(
                {'error': 'Fehlende Parameter. Beispiel: /api?lat=52.10&long=10.10'},
                status=400
            )
            return

        try:
            raw_nodes, cache_status = self.get_nodes_data()
            nodes = json.loads(raw_nodes.decode('utf-8'))
            openmeteo_current = self.fetch_openmeteo_current(user_lat, user_lon)
            selected_node, match_details = self.find_best_matching_node(user_lat, user_lon, nodes, openmeteo_current)

            if not selected_node or not match_details:
                # Fallback nur nach Distanz, falls keine Node komplette Werte hat
                selected_node, distance_km = self.find_nearest_node(user_lat, user_lon, nodes)
                if not selected_node:
                    self.send_json({'error': 'Keine Node mit gültigen Koordinaten gefunden.'}, status=404)
                    return
                match_details = {
                    'distance_km': distance_km,
                    'temp_diff': None,
                }

            response_payload = {
                'lat': user_lat,
                'long': user_lon,
                'node_name': selected_node.get('long_name') or selected_node.get('short_name') or 'Unbekannt',
                'distance_km': round(match_details['distance_km'], 2),
                'temperature': selected_node.get('temperature'),
                'relative_humidity': selected_node.get('relative_humidity'),
                'barometric_pressure': selected_node.get('barometric_pressure'),
                'updated_at': selected_node.get('updated_at'),
                'checked_with_openmeteo': True,
                'check_diff': {
                    'temperature': round(match_details['temp_diff'], 2) if match_details['temp_diff'] is not None else None,
                }
            }

            self.send_json(response_payload, extra_headers={'X-Cache-Status': cache_status})

        except Exception as e:
            print(f"✗ Fehler /api: {e}")
            self.send_json({'error': str(e)}, status=500)
    
    def proxy_nodes(self):
        """Leitet die Anfrage an die API weiter und gibt die Daten zurück (mit Cache)"""
        try:
            data, cache_status = self.get_nodes_data()

            # Antwort mit CORS-Headern senden
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('X-Cache-Status', cache_status)
            self.end_headers()
            self.wfile.write(data)
            
        except Exception as e:
            print(f"✗ Fehler: {e}")
            self.send_error(500, str(e))
    
    def serve_html(self):
        """Serviert die HTML-Seite"""
        html = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lokale Wetterdaten - Meshtastic Nodes</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 500px;
            width: 100%;
        }
        
        h1 {
            color: #333;
            margin-bottom: 30px;
            text-align: center;
            font-size: 2em;
        }
        
        .server-info {
            background: #d4edda;
            border-left: 4px solid #28a745;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
            font-size: 0.9em;
            color: #155724;
        }
        
        .loading {
            text-align: center;
            color: #666;
            padding: 20px;
        }
        
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .weather-card {
            display: none;
        }
        
        .weather-card.active {
            display: block;
            animation: fadeIn 0.5s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .node-info {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 25px;
        }
        
        .node-name {
            font-size: 1.5em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        
        .node-distance {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .weather-data {
            display: grid;
            gap: 20px;
        }
        
        .weather-item {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 15px;
            display: flex;
            align-items: center;
            transition: transform 0.2s;
        }
        
        .weather-item:hover {
            transform: translateX(5px);
        }
        
        .weather-icon {
            font-size: 2em;
            margin-right: 20px;
            width: 50px;
            text-align: center;
        }
        
        .weather-details {
            flex: 1;
        }
        
        .weather-label {
            color: #666;
            font-size: 0.9em;
            margin-bottom: 5px;
        }
        
        .weather-value {
            color: #333;
            font-size: 1.8em;
            font-weight: bold;
        }
        
        .update-time {
            text-align: center;
            color: #999;
            margin-top: 20px;
            font-size: 0.85em;
        }
        
        .cache-status {
            text-align: center;
            color: #28a745;
            margin-top: 10px;
            font-size: 0.8em;
            font-weight: 500;
        }
        
        .error {
            background: #fee;
            color: #c33;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            display: none;
        }
        
        .error.active {
            display: block;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 25px;
            font-size: 1em;
            cursor: pointer;
            margin: 20px auto;
            display: block;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌡️ Lokale Wetterdaten</h1>
        
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Suche nach Ihrem Standort und der nächsten Wetterstation...</p>
        </div>
        
        <div class="error" id="error"></div>
        
        <div class="weather-card" id="weatherCard">
            <div class="node-info">
                <div class="node-name" id="nodeName"></div>
                <div class="node-distance" id="nodeDistance"></div>
            </div>
            
            <div class="weather-data">
                <div class="weather-item">
                    <div class="weather-icon">🌡️</div>
                    <div class="weather-details">
                        <div class="weather-label">Temperatur</div>
                        <div class="weather-value" id="temperature"></div>
                    </div>
                </div>
                
                <div class="weather-item">
                    <div class="weather-icon">💧</div>
                    <div class="weather-details">
                        <div class="weather-label">Luftfeuchtigkeit</div>
                        <div class="weather-value" id="humidity"></div>
                    </div>
                </div>
                
                <div class="weather-item">
                    <div class="weather-icon">🔽</div>
                    <div class="weather-details">
                        <div class="weather-label">Luftdruck</div>
                        <div class="weather-value" id="pressure"></div>
                    </div>
                </div>
            </div>
            
            <div class="update-time" id="updateTime"></div>
            <div class="cache-status" id="cacheStatus"></div>
            
            <button class="refresh-btn" onclick="loadWeatherData()">
                🔄 Aktualisieren
            </button>
        </div>
    </div>

    <script>
        function calculateDistance(lat1, lon1, lat2, lon2) {
            const R = 6371;
            const dLat = (lat2 - lat1) * Math.PI / 180;
            const dLon = (lon2 - lon1) * Math.PI / 180;
            const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                    Math.sin(dLon/2) * Math.sin(dLon/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }
        
        function findBestMatchingNode(userLat, userLon, nodes, referenceTemp, tempTolerance = 2) {
            const validNodes = nodes
                .filter(node => node.latitude && node.longitude &&
                    node.temperature !== null &&
                    node.relative_humidity !== null &&
                    node.barometric_pressure !== null)
                .map(node => ({
                    node,
                    distance: calculateDistance(userLat, userLon, node.latitude, node.longitude),
                    tempDiff: Math.abs(parseFloat(node.temperature) - referenceTemp)
                }));
            
            if (validNodes.length === 0) {
                return { node: null, distance: Infinity };
            }
            
            const matchingNodes = validNodes
                .filter(item => item.tempDiff <= tempTolerance)
                .sort((a, b) => a.distance - b.distance);
            
            if (matchingNodes.length > 0) {
                return { node: matchingNodes[0].node, distance: matchingNodes[0].distance };
            }
            
            const bestFallback = validNodes.sort((a, b) => {
                if (a.tempDiff !== b.tempDiff) {
                    return a.tempDiff - b.tempDiff;
                }
                return a.distance - b.distance;
            })[0];
            
            return { node: bestFallback.node, distance: bestFallback.distance };
        }

        async function fetchOpenMeteoTemperature(lat, lon) {
            const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m`;
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error('Open-Meteo Temperatur konnte nicht geladen werden');
            }
            const data = await response.json();
            return data?.current?.temperature_2m;
        }
        
        function formatUpdateTime(dateString) {
            const date = new Date(dateString);
            return date.toLocaleDateString('de-DE', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }
        
        async function loadWeatherData() {
            const loadingEl = document.getElementById('loading');
            const errorEl = document.getElementById('error');
            const weatherCard = document.getElementById('weatherCard');
            
            loadingEl.style.display = 'block';
            errorEl.classList.remove('active');
            weatherCard.classList.remove('active');
            
            try {
                const position = await new Promise((resolve, reject) => {
                    if (!navigator.geolocation) {
                        reject(new Error('Geolocation wird nicht unterstützt'));
                    }
                    
                    navigator.geolocation.getCurrentPosition(resolve, reject, {
                        enableHighAccuracy: true,
                        timeout: 10000,
                        maximumAge: 0
                    });
                });
                
                const userLat = position.coords.latitude;
                const userLon = position.coords.longitude;
                
                console.log(`Standort: ${userLat}, ${userLon}`);
                
                // Geprüfte Daten direkt über /api abrufen (gleiche Logik wie API)
                const response = await fetch(`/api?lat=${encodeURIComponent(userLat)}&long=${encodeURIComponent(userLon)}`);
                if (!response.ok) {
                    throw new Error('Fehler beim Abrufen der Daten');
                }
                
                // Cache-Status aus Header auslesen
                const cacheStatus = response.headers.get('X-Cache-Status');
                const cacheStatusEl = document.getElementById('cacheStatus');
                if (cacheStatus === 'HIT') {
                    cacheStatusEl.textContent = '⚡ Daten aus Cache (schnell!)';
                    cacheStatusEl.style.color = '#28a745';
                } else {
                    cacheStatusEl.textContent = '🌐 Neue Daten von API geladen';
                    cacheStatusEl.style.color = '#667eea';
                }
                
                const apiData = await response.json();
                if (!apiData || !apiData.node_name) {
                    throw new Error('Keine Station mit gültigen Daten gefunden');
                }
                
                document.getElementById('nodeName').textContent = 
                    apiData.node_name || 'Unbekannt';
                document.getElementById('nodeDistance').textContent = 
                    `${Number(apiData.distance_km).toFixed(1)} km entfernt`;
                document.getElementById('temperature').textContent = 
                    `${parseFloat(apiData.temperature).toFixed(1)}°C`;
                document.getElementById('humidity').textContent = 
                    `${parseFloat(apiData.relative_humidity).toFixed(1)}%`;
                document.getElementById('pressure').textContent = 
                    `${parseFloat(apiData.barometric_pressure).toFixed(1)} hPa`;
                document.getElementById('updateTime').textContent = 
                    `Zuletzt aktualisiert: ${formatUpdateTime(apiData.updated_at)}`;
                
                loadingEl.style.display = 'none';
                weatherCard.classList.add('active');
                
            } catch (error) {
                console.error('Fehler:', error);
                
                let errorMessage = 'Fehler: ';
                if (error.code === 1) {
                    errorMessage += 'Standortzugriff verweigert';
                } else {
                    errorMessage += error.message;
                }
                
                errorEl.textContent = errorMessage;
                errorEl.classList.add('active');
                loadingEl.style.display = 'none';
            }
        }
        
        window.addEventListener('load', loadWeatherData);
    </script>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Überschreibt die Standard-Log-Methode für schönere Ausgabe"""
        print(f"[{self.log_date_time_string()}] {format % args}")

def main():
    PORT = 80
    server = HTTPServer(('0.0.0.0', PORT), WeatherProxyHandler)
    
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║         Meshtastic Wetter-Proxy Server                     ║
    ║                   MIT 5-MINUTEN-CACHE                      ║
    ╠═══════════════════════════════════════════════════════════╣
    ║                                                             ║
    ║  Server läuft auf: http://localhost:{PORT}/                    ║
    ║                                                             ║
    ║  Cache-Dauer: 5 Minuten                                   ║
    ║  Öffnen Sie diese URL in Ihrem Browser!                   ║
    ║  Drücken Sie Ctrl+C zum Beenden                           ║
    ║                                                             ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer wird beendet...")
        server.shutdown()

if __name__ == '__main__':
    main()
