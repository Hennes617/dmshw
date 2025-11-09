#!/usr/bin/env python3
"""
Lokaler Proxy-Server für Meshtastic Wetterdaten
Umgeht CORS-Beschränkungen durch lokalen Server
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
from math import radians, sin, cos, sqrt, atan2

class WeatherProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.serve_html()
        elif self.path == '/nodes':
            self.proxy_nodes()
        else:
            self.send_error(404)
    
    def proxy_nodes(self):
        """Leitet die Anfrage an die API weiter und gibt die Daten zurück"""
        try:
            # Daten von der API abrufen
            with urllib.request.urlopen('https://dmshw.vanix.cloud/nodes') as response:
                data = response.read()
            
            # Antwort mit CORS-Headern senden
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(data)
            
        except Exception as e:
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
        
        function findNearestNode(userLat, userLon, nodes) {
            let nearestNode = null;
            let minDistance = Infinity;
            
            nodes.forEach(node => {
                if (node.latitude && node.longitude && 
                    node.temperature !== null && 
                    node.relative_humidity !== null && 
                    node.barometric_pressure !== null) {
                    
                    const distance = calculateDistance(userLat, userLon, node.latitude, node.longitude);
                    if (distance < minDistance) {
                        minDistance = distance;
                        nearestNode = node;
                    }
                }
            });
            
            return { node: nearestNode, distance: minDistance };
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
                
                // Daten vom lokalen Proxy abrufen
                const response = await fetch('/nodes');
                if (!response.ok) {
                    throw new Error('Fehler beim Abrufen der Daten');
                }
                
                const nodes = await response.json();
                console.log(`${nodes.length} Nodes gefunden`);
                
                const { node: nearestNode, distance } = findNearestNode(userLat, userLon, nodes);
                
                if (!nearestNode) {
                    throw new Error('Keine Station mit gültigen Daten gefunden');
                }
                
                document.getElementById('nodeName').textContent = 
                    nearestNode.long_name || nearestNode.short_name || 'Unbekannt';
                document.getElementById('nodeDistance').textContent = 
                    `${distance.toFixed(1)} km entfernt`;
                document.getElementById('temperature').textContent = 
                    `${parseFloat(nearestNode.temperature).toFixed(1)}°C`;
                document.getElementById('humidity').textContent = 
                    `${parseFloat(nearestNode.relative_humidity).toFixed(1)}%`;
                document.getElementById('pressure').textContent = 
                    `${parseFloat(nearestNode.barometric_pressure).toFixed(1)} hPa`;
                document.getElementById('updateTime').textContent = 
                    `Zuletzt aktualisiert: ${formatUpdateTime(nearestNode.updated_at)}`;
                
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
    server = HTTPServer(('localhost', PORT), WeatherProxyHandler)
    
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║         Meshtastic Wetter-Proxy Server                     ║
    ╠═══════════════════════════════════════════════════════════╣
    ║                                                             ║
    ║  Server läuft auf: http://localhost:{PORT}/                    ║
    ║                                                             ║
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