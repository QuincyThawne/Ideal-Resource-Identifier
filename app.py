"""
Docker Resource Estimator - Flask Web Application

A web interface for testing Docker images and getting cloud instance recommendations.

Routes:
    / - Home page with options
    /bulk-test - Run all default images
    /single-test - Test a custom image
    /results - Display test results
"""

from flask import Flask, render_template_string, request, jsonify, session
import docker
import json
import time
import statistics
import threading
import sys
import io
from datetime import datetime

# Fix encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

app = Flask(__name__)
app.secret_key = 'docker_resource_estimator_secret_key_2025'

# Global variable to store test progress
test_progress = {
    'status': 'idle',
    'current': 0,
    'total': 0,
    'current_image': '',
    'results': []
}

# Global variable to store live test containers
live_containers = {}

# Default test images configuration
DEFAULT_TEST_IMAGES = [
    {"name": "nginx:latest", "command": "nginx -g 'daemon off;'", "description": "Nginx Web Server", "category": "Web Servers"},
    {"name": "httpd:latest", "command": "httpd-foreground", "description": "Apache HTTP Server", "category": "Web Servers"},
    {"name": "redis:latest", "command": "redis-server", "description": "Redis Cache", "category": "Databases"},
    {"name": "postgres:latest", "command": None, "description": "PostgreSQL Database", "category": "Databases", "startup_delay": 5},
    {"name": "mysql:latest", "command": None, "description": "MySQL Database", "category": "Databases"},
    {"name": "python:3.11", "command": "sleep 3600", "description": "Python 3.11", "category": "Languages"},
    {"name": "node:18", "command": "sleep 3600", "description": "Node.js 18", "category": "Languages"},
    {"name": "openjdk:17", "command": "jshell", "description": "OpenJDK 17", "category": "Languages"},
    {"name": "alpine:latest", "command": None, "description": "Alpine Linux", "category": "Base Images"},
    {"name": "ubuntu:latest", "command": None, "description": "Ubuntu Linux", "category": "Base Images"},
]


def estimate_single_image(image_name, test_duration=20, custom_command=None):
    """
    Estimate resources for a single Docker image.
    Returns dict with results or error.
    """
    try:
        client = docker.from_env()
        
        # Check/pull image
        try:
            image = client.images.get(image_name)
        except docker.errors.ImageNotFound:
            try:
                image = client.images.pull(image_name)
            except docker.errors.APIError as e:
                return {"error": f"Failed to pull image: {str(e)}"}
        
        # Start container
        container = None
        try:
            cmd = custom_command if custom_command else "tail -f /dev/null"
            container = client.containers.run(image_name, detach=True, command=cmd)
        except docker.errors.APIError as e:
            # Try fallback commands
            if "executable file not found" in str(e) and not custom_command:
                try:
                    container = client.containers.run(image_name, detach=True, command="sleep infinity")
                except:
                    try:
                        container = client.containers.run(image_name, detach=True)
                    except Exception as final_e:
                        return {"error": f"Failed to start container: {str(final_e)}"}
            else:
                return {"error": f"Failed to start container: {str(e)}"}
        
        # Collect stats
        cpu_usages = []
        mem_usages = []
        
        try:
            stats_stream = container.stats(stream=True)
            start = time.time()
            sample_count = 0
            
            while time.time() - start < test_duration:
                try:
                    # Check if container is still running
                    container.reload()
                    if container.status != 'running':
                        break
                    
                    stats_raw = next(stats_stream)
                    
                    # Decode stats if bytes
                    if isinstance(stats_raw, bytes):
                        stats = json.loads(stats_raw.decode('utf-8'))
                    else:
                        stats = stats_raw
                    
                    # CPU calculation
                    cpu_stats = stats.get("cpu_stats", {})
                    precpu_stats = stats.get("precpu_stats", {})
                    
                    cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                    precpu_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                    
                    system_cpu = cpu_stats.get("system_cpu_usage", 0)
                    presystem_cpu = precpu_stats.get("system_cpu_usage", 0)
                    
                    cpu_delta = cpu_total - precpu_total
                    system_delta = system_cpu - presystem_cpu
                    
                    online_cpus = cpu_stats.get("online_cpus")
                    if not online_cpus:
                        percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
                        online_cpus = len(percpu_usage) if percpu_usage else 1
                    
                    if system_delta > 0 and cpu_delta >= 0:
                        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                        cpu_usages.append(cpu_percent)
                    
                    # Memory
                    mem_usage = stats.get("memory_stats", {}).get("usage", 0) / (1024 ** 2)
                    mem_usages.append(mem_usage)
                    
                    sample_count += 1
                    time.sleep(1)
                    
                except (StopIteration, KeyError):
                    break
                    
        finally:
            if container:
                try:
                    container.stop()
                    container.remove()
                except:
                    pass
        
        # Calculate results
        if not cpu_usages or not mem_usages:
            return {"error": "No stats collected. Container may have exited too early."}
        
        avg_cpu = statistics.mean(cpu_usages)
        peak_cpu = max(cpu_usages)
        avg_mem = statistics.mean(mem_usages)
        peak_mem = max(mem_usages)
        
        recommended_vcpu = max(1, round(peak_cpu / 80))
        recommended_ram = round(peak_mem * 1.5 / 1024, 2)
        
        # Instance recommendations
        instances = get_instance_recommendations(recommended_vcpu, recommended_ram)
        
        return {
            "image": image_name,
            "duration_sec": test_duration,
            "cpu_avg": round(avg_cpu, 2),
            "cpu_peak": round(peak_cpu, 2),
            "mem_avg_mb": round(avg_mem, 2),
            "mem_peak_mb": round(peak_mem, 2),
            "recommendation": {
                "vcpu": recommended_vcpu,
                "ram_gb": recommended_ram
            },
            "instances": instances,
            "samples": sample_count
        }
        
    except Exception as e:
        return {"error": str(e)}


def get_instance_recommendations(vcpu, ram_gb):
    """Get cloud instance recommendations based on vCPU and RAM."""
    if vcpu == 1 and ram_gb <= 1:
        return {
            "aws": "t3.micro",
            "gcp": "e2-micro",
            "azure": "B1s"
        }
    elif vcpu == 1 and ram_gb <= 2:
        return {
            "aws": "t3.small",
            "gcp": "e2-small",
            "azure": "B1ms"
        }
    elif vcpu == 2:
        return {
            "aws": "t3.medium",
            "gcp": "e2-medium",
            "azure": "B2s"
        }
    else:
        return {
            "aws": "t3.large+",
            "gcp": "e2-standard+",
            "azure": "B2ms+"
        }


def run_bulk_tests(duration=20):
    """Run tests on all default images."""
    global test_progress
    
    test_progress['status'] = 'running'
    test_progress['total'] = len(DEFAULT_TEST_IMAGES)
    test_progress['current'] = 0
    test_progress['results'] = []
    
    for idx, image_config in enumerate(DEFAULT_TEST_IMAGES, 1):
        test_progress['current'] = idx
        test_progress['current_image'] = image_config['name']
        
        result = estimate_single_image(
            image_config['name'],
            duration,
            image_config.get('command')
        )
        
        if 'error' not in result:
            result['description'] = image_config['description']
            result['category'] = image_config['category']
        
        test_progress['results'].append(result)
        time.sleep(1)  # Small delay between tests
    
    test_progress['status'] = 'complete'


# HTML Templates
HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Docker Resource Estimator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            color: white;
            margin-bottom: 50px;
        }
        
        h1 {
            font-size: 3em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .subtitle {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 30px;
            margin-top: 40px;
        }
        
        .card {
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            transition: transform 0.3s, box-shadow 0.3s;
            cursor: pointer;
        }
        
        .card:hover {
            transform: translateY(-10px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.4);
        }
        
        .card-icon {
            font-size: 4em;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .card h2 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.8em;
        }
        
        .card p {
            color: #666;
            line-height: 1.6;
            margin-bottom: 20px;
        }
        
        .btn {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 30px;
            border-radius: 25px;
            text-decoration: none;
            transition: all 0.3s;
            border: none;
            cursor: pointer;
            font-size: 1em;
            font-weight: bold;
        }
        
        .btn:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .features {
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 30px;
            margin-top: 50px;
            color: white;
        }
        
        .features h3 {
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        
        .features ul {
            list-style: none;
        }
        
        .features li {
            padding: 10px 0;
            padding-left: 30px;
            position: relative;
        }
        
        .features li:before {
            content: "✓";
            position: absolute;
            left: 0;
            font-weight: bold;
            color: #4ade80;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🐳 Docker Resource Estimator</h1>
            <p class="subtitle">Profile Docker containers and get cloud instance recommendations</p>
        </header>
        
        <div class="cards">
            <div class="card" onclick="window.location.href='/bulk-test'">
                <div class="card-icon">📊</div>
                <h2>Bulk Test</h2>
                <p>Test all 10 default Docker images including Nginx, Redis, MySQL, Python, Node.js, and more.</p>
                <p><strong>Estimated time:</strong> ~4-5 minutes</p>
                <button class="btn">Run All Tests</button>
            </div>
            
            <div class="card" onclick="window.location.href='/single-test'">
                <div class="card-icon">🎯</div>
                <h2>Single Image Test</h2>
                <p>Test a specific Docker image of your choice. Enter any image name from Docker Hub.</p>
                <p><strong>Estimated time:</strong> ~30 seconds</p>
                <button class="btn">Test Custom Image</button>
            </div>
            
            <div class="card" onclick="window.location.href='/live-test'">
                <div class="card-icon">📡</div>
                <h2>Live Monitoring</h2>
                <p>Run a Docker container and monitor real-time CPU and memory usage with live updates.</p>
                <p><strong>Duration:</strong> Until you stop it</p>
                <button class="btn">Start Live Monitor</button>
            </div>
        </div>
        
        <div class="features">
            <h3>Features</h3>
            <ul>
                <li>Accurate CPU and memory profiling using Docker stats API</li>
                <li>Cloud instance recommendations for AWS, GCP, and Azure</li>
                <li>Real-time progress tracking</li>
                <li>Comprehensive test reports with comparison tables</li>
                <li>Support for custom Docker images and commands</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

BULK_TEST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bulk Test - Docker Resource Estimator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 30px;
            text-align: center;
        }
        
        .config-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #333;
        }
        
        input, select {
            width: 100%;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 1em;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border-radius: 25px;
            border: none;
            cursor: pointer;
            font-size: 1.1em;
            font-weight: bold;
            width: 100%;
            transition: all 0.3s;
        }
        
        .btn:hover {
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .progress-section {
            display: none;
            margin-top: 30px;
        }
        
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin-bottom: 20px;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
        }
        
        .current-test {
            text-align: center;
            padding: 20px;
            background: #f0f0f0;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
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
        
        .back-btn {
            display: inline-block;
            margin-top: 20px;
            color: #667eea;
            text-decoration: none;
            font-weight: bold;
        }
        
        .back-btn:hover {
            text-decoration: underline;
        }
        
        .image-list {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .image-list h3 {
            margin-bottom: 15px;
            color: #667eea;
        }
        
        .image-list ul {
            list-style: none;
            columns: 2;
        }
        
        .image-list li {
            padding: 5px 0;
            padding-left: 20px;
            position: relative;
        }
        
        .image-list li:before {
            content: "🐳";
            position: absolute;
            left: 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Bulk Test - All Default Images</h1>
        
        <div class="image-list">
            <h3>Images to be tested (10):</h3>
            <ul>
                <li>nginx:latest (Nginx Web Server)</li>
                <li>httpd:latest (Apache)</li>
                <li>redis:latest (Redis Cache)</li>
                <li>postgres:latest (PostgreSQL)</li>
                <li>mysql:latest (MySQL)</li>
                <li>python:3.11 (Python)</li>
                <li>node:18 (Node.js)</li>
                <li>openjdk:17 (Java)</li>
                <li>alpine:latest (Alpine Linux)</li>
                <li>ubuntu:latest (Ubuntu)</li>
            </ul>
        </div>
        
        <div class="config-section">
            <div class="form-group">
                <label for="duration">Test Duration per Image (seconds):</label>
                <input type="number" id="duration" value="20" min="10" max="120">
                <small style="color: #666; display: block; margin-top: 5px;">
                    Recommended: 20-30 seconds. Total time ≈ duration × 10 images
                </small>
            </div>
            
            <button class="btn" id="startBtn" onclick="startBulkTest()">
                🚀 Start Bulk Test
            </button>
        </div>
        
        <div class="progress-section" id="progressSection">
            <div class="progress-bar">
                <div class="progress-fill" id="progressFill" style="width: 0%">0%</div>
            </div>
            
            <div class="current-test">
                <div class="spinner"></div>
                <p><strong>Testing:</strong> <span id="currentImage">-</span></p>
                <p><span id="currentProgress">0</span> of <span id="totalImages">10</span> completed</p>
            </div>
        </div>
        
        <a href="/" class="back-btn">← Back to Home</a>
    </div>
    
    <script>
        let checkInterval;
        
        function startBulkTest() {
            const duration = document.getElementById('duration').value;
            const startBtn = document.getElementById('startBtn');
            const progressSection = document.getElementById('progressSection');
            
            // Disable button and show progress
            startBtn.disabled = true;
            startBtn.textContent = 'Testing in progress...';
            progressSection.style.display = 'block';
            
            // Start the test
            fetch('/api/start-bulk-test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({duration: parseInt(duration)})
            });
            
            // Poll for progress
            checkInterval = setInterval(checkProgress, 1000);
        }
        
        function checkProgress() {
            fetch('/api/bulk-test-progress')
                .then(response => response.json())
                .then(data => {
                    const percent = (data.current / data.total) * 100;
                    document.getElementById('progressFill').style.width = percent + '%';
                    document.getElementById('progressFill').textContent = Math.round(percent) + '%';
                    document.getElementById('currentImage').textContent = data.current_image || 'Waiting...';
                    document.getElementById('currentProgress').textContent = data.current;
                    document.getElementById('totalImages').textContent = data.total;
                    
                    if (data.status === 'complete') {
                        clearInterval(checkInterval);
                        window.location.href = '/results?type=bulk';
                    }
                });
        }
    </script>
</body>
</html>
"""

SINGLE_TEST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Single Image Test - Docker Resource Estimator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 30px;
            text-align: center;
        }
        
        .form-group {
            margin-bottom: 25px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
            color: #333;
        }
        
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        
        input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        small {
            display: block;
            margin-top: 5px;
            color: #666;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border-radius: 25px;
            border: none;
            cursor: pointer;
            font-size: 1.1em;
            font-weight: bold;
            width: 100%;
            transition: all 0.3s;
            margin-top: 20px;
        }
        
        .btn:hover:not(:disabled) {
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .progress-section {
            display: none;
            margin-top: 30px;
            padding: 30px;
            background: #f8f9fa;
            border-radius: 10px;
            text-align: center;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .back-btn {
            display: inline-block;
            margin-top: 20px;
            color: #667eea;
            text-decoration: none;
            font-weight: bold;
        }
        
        .back-btn:hover {
            text-decoration: underline;
        }
        
        .examples {
            background: #f0f7ff;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
        }
        
        .examples strong {
            color: #667eea;
        }
        
        .examples code {
            background: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Single Image Test</h1>
        
        <form onsubmit="startSingleTest(event)">
            <div class="form-group">
                <label for="imageName">Docker Image Name:</label>
                <input 
                    type="text" 
                    id="imageName" 
                    placeholder="e.g., nginx:latest or redis:7-alpine" 
                    required
                >
                <small>Enter any public Docker image from Docker Hub</small>
                
                <div class="examples">
                    <strong>Popular examples:</strong><br>
                    <code>nginx:latest</code>, 
                    <code>redis:latest</code>, 
                    <code>postgres:14</code>, 
                    <code>mongo:latest</code>, 
                    <code>elasticsearch:8.11.0</code>
                </div>
            </div>
            
            <div class="form-group">
                <label for="duration">Test Duration (seconds):</label>
                <input 
                    type="number" 
                    id="duration" 
                    value="30" 
                    min="10" 
                    max="120"
                    required
                >
                <small>Recommended: 20-30 seconds for accurate results</small>
            </div>
            
            <div class="form-group">
                <label for="command">Custom Command (optional):</label>
                <input 
                    type="text" 
                    id="command" 
                    placeholder="e.g., nginx -g 'daemon off;' or leave empty"
                >
                <small>Leave empty to use default keep-alive command</small>
            </div>
            
            <button type="submit" class="btn" id="testBtn">
                🚀 Start Test
            </button>
        </form>
        
        <div class="progress-section" id="progressSection">
            <div class="spinner"></div>
            <h3>Testing in progress...</h3>
            <p id="statusText">Pulling image and starting container...</p>
        </div>
        
        <a href="/" class="back-btn">← Back to Home</a>
    </div>
    
    <script>
        function startSingleTest(event) {
            event.preventDefault();
            
            const imageName = document.getElementById('imageName').value;
            const duration = document.getElementById('duration').value;
            const command = document.getElementById('command').value;
            const testBtn = document.getElementById('testBtn');
            const progressSection = document.getElementById('progressSection');
            
            // Show progress
            testBtn.disabled = true;
            testBtn.textContent = 'Testing...';
            progressSection.style.display = 'block';
            
            // Submit test
            fetch('/api/start-single-test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    image: imageName,
                    duration: parseInt(duration),
                    command: command || null
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    window.location.href = '/results?type=single';
                } else {
                    alert('Test failed: ' + (data.error || 'Unknown error'));
                    testBtn.disabled = false;
                    testBtn.textContent = '🚀 Start Test';
                    progressSection.style.display = 'none';
                }
            })
            .catch(error => {
                alert('Error: ' + error);
                testBtn.disabled = false;
                testBtn.textContent = '🚀 Start Test';
                progressSection.style.display = 'none';
            });
        }
    </script>
</body>
</html>
"""

LIVE_TEST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Monitoring - Docker Resource Estimator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 30px;
            text-align: center;
        }
        
        .form-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
            color: #333;
        }
        
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
        }
        
        small {
            display: block;
            margin-top: 5px;
            color: #666;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border-radius: 25px;
            border: none;
            cursor: pointer;
            font-size: 1.1em;
            font-weight: bold;
            width: 100%;
            transition: all 0.3s;
        }
        
        .btn:hover:not(:disabled) {
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .btn.danger {
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        }
        
        .stats-section {
            display: none;
            margin-top: 30px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: bold;
            margin-bottom: 20px;
        }
        
        .status-badge.running {
            background: #10b981;
            color: white;
        }
        
        .status-badge.stopped {
            background: #ef4444;
            color: white;
        }
        
        .container-info {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        
        .container-info h3 {
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #ddd;
        }
        
        .info-row:last-child {
            border-bottom: none;
        }
        
        .info-label {
            font-weight: bold;
            color: #666;
        }
        
        .info-value {
            color: #333;
            font-family: monospace;
        }
        
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .metric-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 10px;
            text-align: center;
        }
        
        .metric-label {
            font-size: 1em;
            opacity: 0.9;
            margin-bottom: 10px;
        }
        
        .metric-value {
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .metric-sub {
            font-size: 0.9em;
            opacity: 0.8;
        }
        
        .chart-container {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .chart-container h3 {
            color: #667eea;
            margin-bottom: 15px;
        }
        
        .chart {
            height: 200px;
            background: white;
            border-radius: 8px;
            padding: 15px;
            position: relative;
            overflow: hidden;
        }
        
        .chart-line {
            stroke: #667eea;
            stroke-width: 2;
            fill: none;
        }
        
        .chart-area {
            fill: rgba(102, 126, 234, 0.1);
        }
        
        .back-btn {
            display: inline-block;
            margin-top: 20px;
            color: #667eea;
            text-decoration: none;
            font-weight: bold;
        }
        
        .back-btn:hover {
            text-decoration: underline;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
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
        
        .history {
            margin-top: 20px;
            font-size: 0.9em;
            color: #666;
        }
        
        .history-item {
            padding: 5px 0;
            display: flex;
            justify-content: space-between;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📡 Live Container Monitoring</h1>
        
        <div class="form-section" id="formSection">
            <div class="form-group">
                <label for="presetSelect">Quick Preset (optional):</label>
                <select id="presetSelect" onchange="loadPreset()" style="width: 100%; padding: 12px; border: 2px solid #ddd; border-radius: 8px; font-size: 1em;">
                    <option value="">-- Select a preset or enter custom --</option>
                    <option value="mobsf">MobSF - Mobile Security Framework (Port 8000)</option>
                    <option value="nginx">Nginx Web Server (Port 80)</option>
                    <option value="apache">Apache Web Server (Port 80)</option>
                    <option value="redis">Redis Cache (Port 6379)</option>
                    <option value="postgres">PostgreSQL Database (Port 5432)</option>
                    <option value="mysql">MySQL Database (Port 3306)</option>
                    <option value="mongo">MongoDB (Port 27017)</option>
                    <option value="elasticsearch">Elasticsearch (Port 9200)</option>
                </select>
                <small>Select a preset to auto-fill image, command, and port settings</small>
            </div>
            
            <div class="form-group">
                <label for="imageName">Docker Image Name:</label>
                <input 
                    type="text" 
                    id="imageName" 
                    placeholder="e.g., nginx:latest or opensecurity/mobile-security-framework-mobsf:latest" 
                    value=""
                >
                <small>Enter any public Docker image from Docker Hub</small>
            </div>
            
            <div class="form-group">
                <label for="command">Custom Command (optional):</label>
                <input 
                    type="text" 
                    id="command" 
                    placeholder="e.g., nginx -g 'daemon off;' or leave empty"
                >
                <small>Leave empty to use default keep-alive command</small>
            </div>
            
            <div class="form-group">
                <label for="portMapping">Port Mapping (optional):</label>
                <input 
                    type="text" 
                    id="portMapping" 
                    placeholder="e.g., 8000:8000 or 80:8080"
                >
                <small>Map container ports to host (format: host_port:container_port)</small>
            </div>
            
            <div id="presetInfo" style="display: none; background: #e8f4ff; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #667eea;">
                <strong>ℹ️ Preset Info:</strong>
                <p id="presetInfoText" style="margin-top: 8px; color: #333;"></p>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #ffc107;">
                <strong>⚠️ Troubleshooting Tips:</strong>
                <ul style="margin-top: 8px; margin-left: 20px; color: #856404;">
                    <li>Ensure Docker Desktop is running on Windows</li>
                    <li>For MobSF: Wait 30-60 seconds after starting for service to be ready</li>
                    <li>Check container logs below for startup errors</li>
                    <li>If port is in use, change the host port (e.g., 8001:8000)</li>
                    <li>Some containers need time to initialize - watch the logs!</li>
                </ul>
            </div>
            
            <button class="btn" id="startBtn" onclick="startLiveTest()">🚀 Start Container</button>
        </div>
        
        <div class="stats-section" id="statsSection">
            <div style="text-align: center; margin-bottom: 20px;">
                <span class="status-badge running" id="statusBadge">● Running</span>
            </div>
            
            <div class="container-info">
                <h3>Container Information</h3>
                <div class="info-row">
                    <span class="info-label">Image:</span>
                    <span class="info-value" id="infoImage">-</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Container ID:</span>
                    <span class="info-value" id="infoContainerId">-</span>
                </div>
                <div class="info-row" id="accessUrlRow" style="display: none;">
                    <span class="info-label">Access URL:</span>
                    <span class="info-value">
                        <a href="" id="accessUrl" target="_blank" style="color: #667eea; text-decoration: underline;">Open in New Tab</a>
                    </span>
                </div>
                <div class="info-row">
                    <span class="info-label">Running Time:</span>
                    <span class="info-value" id="infoRuntime">0s</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Samples Collected:</span>
                    <span class="info-value" id="infoSamples">0</span>
                </div>
            </div>
            
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-label">CPU Usage</div>
                    <div class="metric-value" id="cpuCurrent">0%</div>
                    <div class="metric-sub">Peak: <span id="cpuPeak">0%</span> | Avg: <span id="cpuAvg">0%</span></div>
                </div>
                
                <div class="metric-card">
                    <div class="metric-label">Memory Usage</div>
                    <div class="metric-value" id="memCurrent">0 MB</div>
                    <div class="metric-sub">Peak: <span id="memPeak">0 MB</span> | Avg: <span id="memAvg">0 MB</span></div>
                </div>
            </div>
            
            <div class="chart-container">
                <h3>CPU Usage Over Time</h3>
                <div class="chart" id="cpuChart">
                    <svg width="100%" height="100%" id="cpuSvg"></svg>
                </div>
                <div class="history" id="cpuHistory"></div>
            </div>
            
            <div class="chart-container">
                <h3>Memory Usage Over Time</h3>
                <div class="chart" id="memChart">
                    <svg width="100%" height="100%" id="memSvg"></svg>
                </div>
                <div class="history" id="memHistory"></div>
            </div>
            
            <div class="chart-container">
                <h3>📟 Container Output (Live Logs)</h3>
                <div style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 0.9em; height: 300px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word;" id="terminalOutput">
                    <span style="color: #888;">Waiting for container output...</span>
                </div>
                <div style="margin-top: 10px; text-align: right;">
                    <button onclick="clearTerminal()" style="background: #333; color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer;">Clear Output</button>
                    <button onclick="toggleAutoScroll()" id="autoScrollBtn" style="background: #667eea; color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; margin-left: 10px;">Auto-scroll: ON</button>
                </div>
            </div>
            
            <div id="recommendationSection" style="display: none; margin-top: 30px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 10px;">
                    <h3 style="margin-bottom: 20px; font-size: 1.5em;">☁️ Recommended Cloud Instance</h3>
                    
                    <div style="background: rgba(255,255,255,0.1); padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                        <div style="font-size: 1.2em; margin-bottom: 15px;">
                            <strong>Recommended Configuration:</strong>
                        </div>
                        <div style="font-size: 1.8em; font-weight: bold;">
                            <span id="recVcpu">-</span> vCPU(s), <span id="recRam">-</span> GB RAM
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <strong>Test Summary:</strong>
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 10px;">
                            <div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 5px;">
                                <div style="opacity: 0.9; font-size: 0.9em;">Peak CPU</div>
                                <div style="font-size: 1.3em; font-weight: bold;" id="recCpuPeak">-</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 5px;">
                                <div style="opacity: 0.9; font-size: 0.9em;">Peak Memory</div>
                                <div style="font-size: 1.3em; font-weight: bold;" id="recMemPeak">-</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 5px;">
                                <div style="opacity: 0.9; font-size: 0.9em;">Avg CPU</div>
                                <div style="font-size: 1.3em; font-weight: bold;" id="recCpuAvg">-</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.1); padding: 12px; border-radius: 5px;">
                                <div style="opacity: 0.9; font-size: 0.9em;">Avg Memory</div>
                                <div style="font-size: 1.3em; font-weight: bold;" id="recMemAvg">-</div>
                            </div>
                        </div>
                        <div style="margin-top: 10px; opacity: 0.9;">
                            <span id="recSamples">-</span> samples collected over <span id="recDuration">-</span> seconds
                        </div>
                    </div>
                    
                    <div>
                        <strong style="font-size: 1.1em;">Cloud Provider Recommendations:</strong>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-top: 15px;">
                            <div style="background: rgba(255,255,255,0.2); padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 0.9em; opacity: 0.9; margin-bottom: 5px;">AWS</div>
                                <div style="font-size: 1.2em; font-weight: bold;" id="recAws">-</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.2); padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 0.9em; opacity: 0.9; margin-bottom: 5px;">Google Cloud</div>
                                <div style="font-size: 1.2em; font-weight: bold;" id="recGcp">-</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.2); padding: 15px; border-radius: 8px; text-align: center;">
                                <div style="font-size: 0.9em; opacity: 0.9; margin-bottom: 5px;">Azure</div>
                                <div style="font-size: 1.2em; font-weight: bold;" id="recAzure">-</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <button class="btn danger" id="stopBtn" onclick="stopLiveTest()">⏹️ Stop Container</button>
        </div>
        
        <a href="/" class="back-btn">← Back to Home</a>
    </div>
    
    <script>
        let pollInterval;
        let containerId;
        let startTime;
        let cpuData = [];
        let memData = [];
        let maxDataPoints = 60;
        let autoScroll = true;
        let lastLogLength = 0;
        
        const presets = {
            mobsf: {
                image: 'opensecurity/mobile-security-framework-mobsf:latest',
                command: '',
                port: '8000:8000',
                info: 'MobSF (Mobile Security Framework) - An automated, all-in-one mobile application security assessment framework. Access at http://localhost:8000 with credentials mobsf/mobsf. Perfect for stress testing mobile app analysis workloads.'
            },
            nginx: {
                image: 'nginx:latest',
                command: "nginx -g 'daemon off;'",
                port: '80:80',
                info: 'Nginx - High-performance web server and reverse proxy. Access at http://localhost:80. Great for testing web serving performance.'
            },
            apache: {
                image: 'httpd:latest',
                command: 'httpd-foreground',
                port: '80:80',
                info: 'Apache HTTP Server - Popular open-source web server. Access at http://localhost:80.'
            },
            redis: {
                image: 'redis:latest',
                command: 'redis-server',
                port: '6379:6379',
                info: 'Redis - In-memory data structure store used as cache and message broker. Connect at localhost:6379.'
            },
            postgres: {
                image: 'postgres:latest',
                command: '',
                port: '5432:5432',
                info: 'PostgreSQL - Advanced open-source relational database. Connect at localhost:5432. Note: Set POSTGRES_PASSWORD env var for production.'
            },
            mysql: {
                image: 'mysql:latest',
                command: '',
                port: '3306:3306',
                info: 'MySQL - Popular open-source relational database. Connect at localhost:3306. Note: Set MYSQL_ROOT_PASSWORD env var for production.'
            },
            mongo: {
                image: 'mongo:latest',
                command: '',
                port: '27017:27017',
                info: 'MongoDB - NoSQL document database. Connect at localhost:27017.'
            },
            elasticsearch: {
                image: 'elasticsearch:8.11.0',
                command: '',
                port: '9200:9200',
                info: 'Elasticsearch - Distributed search and analytics engine. Access at http://localhost:9200.'
            }
        };
        
        function loadPreset() {
            const select = document.getElementById('presetSelect');
            const presetKey = select.value;
            
            if (!presetKey) {
                document.getElementById('presetInfo').style.display = 'none';
                return;
            }
            
            const preset = presets[presetKey];
            document.getElementById('imageName').value = preset.image;
            document.getElementById('command').value = preset.command;
            document.getElementById('portMapping').value = preset.port;
            document.getElementById('presetInfoText').textContent = preset.info;
            document.getElementById('presetInfo').style.display = 'block';
        }
        
        function startLiveTest() {
            const imageName = document.getElementById('imageName').value;
            const command = document.getElementById('command').value;
            const portMapping = document.getElementById('portMapping').value;
            const startBtn = document.getElementById('startBtn');
            const formSection = document.getElementById('formSection');
            const statsSection = document.getElementById('statsSection');
            
            if (!imageName) {
                alert('Please enter an image name');
                return;
            }
            
            startBtn.disabled = true;
            startBtn.innerHTML = '<div class="spinner" style="width: 20px; height: 20px; border-width: 3px; margin: 0 auto;"></div>';
            
            fetch('/api/start-live-test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    image: imageName,
                    command: command || null,
                    port_mapping: portMapping || null
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    containerId = data.container_id;
                    startTime = Date.now();
                    cpuData = [];
                    memData = [];
                    lastLogLength = 0;
                    
                    document.getElementById('infoImage').textContent = imageName;
                    document.getElementById('infoContainerId').textContent = containerId.substring(0, 12);
                    
                    // Show port mapping and access URL if available
                    if (data.port_info) {
                        document.getElementById('infoImage').textContent = imageName + ' ' + data.port_info;
                        
                        // Extract port and create clickable link
                        const portMatch = portMapping.match(/^(\d+):/);
                        if (portMatch) {
                            const port = portMatch[1];
                            const url = `http://localhost:${port}`;
                            document.getElementById('accessUrl').href = url;
                            document.getElementById('accessUrl').textContent = url;
                            document.getElementById('accessUrlRow').style.display = 'flex';
                        }
                    }
                    
                    formSection.style.display = 'none';
                    statsSection.style.display = 'block';
                    
                    pollInterval = setInterval(pollStats, 1000);
                } else {
                    alert('Failed to start container: ' + (data.error || 'Unknown error'));
                    startBtn.disabled = false;
                    startBtn.textContent = '🚀 Start Container';
                }
            })
            .catch(error => {
                alert('Error: ' + error);
                startBtn.disabled = false;
                startBtn.textContent = '🚀 Start Container';
            });
        }
        
        function pollStats() {
            if (!containerId) return;
            
            fetch('/api/live-test-stats?container_id=' + containerId)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'error') {
                        clearInterval(pollInterval);
                        document.getElementById('statusBadge').className = 'status-badge stopped';
                        document.getElementById('statusBadge').textContent = '● Stopped';
                        alert('Container stopped: ' + data.error);
                        return;
                    }
                    
                    // Update runtime
                    const runtime = Math.floor((Date.now() - startTime) / 1000);
                    document.getElementById('infoRuntime').textContent = runtime + 's';
                    document.getElementById('infoSamples').textContent = data.samples;
                    
                    // Update CPU
                    document.getElementById('cpuCurrent').textContent = data.cpu_current.toFixed(2) + '%';
                    document.getElementById('cpuPeak').textContent = data.cpu_peak.toFixed(2) + '%';
                    document.getElementById('cpuAvg').textContent = data.cpu_avg.toFixed(2) + '%';
                    
                    // Update Memory
                    document.getElementById('memCurrent').textContent = data.mem_current.toFixed(2) + ' MB';
                    document.getElementById('memPeak').textContent = data.mem_peak.toFixed(2) + ' MB';
                    document.getElementById('memAvg').textContent = data.mem_avg.toFixed(2) + ' MB';
                    
                    // Store data
                    cpuData.push(data.cpu_current);
                    memData.push(data.mem_current);
                    
                    if (cpuData.length > maxDataPoints) {
                        cpuData.shift();
                        memData.shift();
                    }
                    
                    // Update charts
                    updateChart('cpuSvg', cpuData, 100, '#667eea');
                    updateChart('memSvg', memData, Math.max(...memData) * 1.2, '#764ba2');
                    
                    // Update history
                    updateHistory('cpuHistory', cpuData.slice(-5), '%');
                    updateHistory('memHistory', memData.slice(-5), ' MB');
                    
                    // Update terminal output
                    if (data.logs && data.logs.length > lastLogLength) {
                        const terminalOutput = document.getElementById('terminalOutput');
                        if (lastLogLength === 0) {
                            terminalOutput.innerHTML = '';
                        }
                        terminalOutput.textContent = data.logs;
                        lastLogLength = data.logs.length;
                        
                        if (autoScroll) {
                            terminalOutput.scrollTop = terminalOutput.scrollHeight;
                        }
                    }
                });
        }
        
        function clearTerminal() {
            document.getElementById('terminalOutput').innerHTML = '<span style="color: #888;">Terminal cleared. New output will appear here...</span>';
            lastLogLength = 0;
        }
        
        function toggleAutoScroll() {
            autoScroll = !autoScroll;
            const btn = document.getElementById('autoScrollBtn');
            btn.textContent = 'Auto-scroll: ' + (autoScroll ? 'ON' : 'OFF');
            btn.style.background = autoScroll ? '#667eea' : '#666';
        }
        
        function updateChart(svgId, data, maxVal, color) {
            const svg = document.getElementById(svgId);
            const width = svg.clientWidth;
            const height = svg.clientHeight;
            
            if (data.length < 2) return;
            
            const xStep = width / (maxDataPoints - 1);
            const yScale = height / maxVal;
            
            let pathData = 'M 0 ' + (height - data[0] * yScale);
            for (let i = 1; i < data.length; i++) {
                const x = i * xStep;
                const y = height - data[i] * yScale;
                pathData += ' L ' + x + ' ' + y;
            }
            
            let areaData = pathData + ' L ' + ((data.length - 1) * xStep) + ' ' + height + ' L 0 ' + height + ' Z';
            
            svg.innerHTML = `
                <path d="${areaData}" fill="${color}" opacity="0.2"/>
                <path d="${pathData}" stroke="${color}" stroke-width="2" fill="none"/>
            `;
        }
        
        function updateHistory(elementId, data, unit) {
            const element = document.getElementById(elementId);
            const reversed = data.slice().reverse();
            element.innerHTML = reversed.map((val, idx) => 
                `<div class="history-item">
                    <span>${reversed.length - idx} sample(s) ago:</span>
                    <span><strong>${val.toFixed(2)}${unit}</strong></span>
                </div>`
            ).join('');
        }
        
        function stopLiveTest() {
            if (!containerId) return;
            
            if (!confirm('Are you sure you want to stop the container?')) {
                return;
            }
            
            clearInterval(pollInterval);
            
            fetch('/api/stop-live-test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({container_id: containerId})
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('statusBadge').className = 'status-badge stopped';
                document.getElementById('statusBadge').textContent = '● Stopped';
                document.getElementById('stopBtn').disabled = true;
                
                // Display recommendations if available
                if (data.recommendations) {
                    const rec = data.recommendations;
                    const stats = rec.stats;
                    
                    document.getElementById('recVcpu').textContent = rec.vcpu;
                    document.getElementById('recRam').textContent = rec.ram_gb;
                    document.getElementById('recCpuPeak').textContent = stats.cpu_peak + '%';
                    document.getElementById('recMemPeak').textContent = stats.mem_peak_mb.toFixed(2) + ' MB';
                    document.getElementById('recCpuAvg').textContent = stats.cpu_avg + '%';
                    document.getElementById('recMemAvg').textContent = stats.mem_avg_mb.toFixed(2) + ' MB';
                    document.getElementById('recSamples').textContent = stats.samples;
                    document.getElementById('recDuration').textContent = stats.duration_sec;
                    document.getElementById('recAws').textContent = rec.instances.aws;
                    document.getElementById('recGcp').textContent = rec.instances.gcp;
                    document.getElementById('recAzure').textContent = rec.instances.azure;
                    
                    document.getElementById('recommendationSection').style.display = 'block';
                    
                    // Scroll to recommendations
                    document.getElementById('recommendationSection').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
                
                alert('Container stopped successfully! See recommendations below.');
            })
            .catch(error => {
                alert('Error stopping container: ' + error);
            });
        }
    </script>
</body>
</html>
"""

RESULTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Results - Docker Resource Estimator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #667eea;
            margin-bottom: 10px;
            text-align: center;
        }
        
        .summary {
            text-align: center;
            margin-bottom: 30px;
            color: #666;
        }
        
        .result-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
            border-left: 5px solid #667eea;
        }
        
        .result-card.error {
            border-left-color: #ef4444;
            background: #fee;
        }
        
        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .result-header h2 {
            color: #667eea;
            font-size: 1.4em;
        }
        
        .badge {
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }
        
        .badge.success {
            background: #10b981;
            color: white;
        }
        
        .badge.error {
            background: #ef4444;
            color: white;
        }
        
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .metric {
            background: white;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-label {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }
        
        .metric-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }
        
        .recommendation {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-top: 15px;
        }
        
        .recommendation h3 {
            margin-bottom: 15px;
        }
        
        .instances {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
        }
        
        .instance {
            background: rgba(255,255,255,0.2);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        
        .instance-provider {
            font-size: 0.9em;
            opacity: 0.9;
            margin-bottom: 5px;
        }
        
        .instance-type {
            font-size: 1.2em;
            font-weight: bold;
        }
        
        .actions {
            margin-top: 30px;
            text-align: center;
        }
        
        .btn {
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 30px;
            border-radius: 25px;
            text-decoration: none;
            margin: 0 10px;
            transition: all 0.3s;
            border: none;
            cursor: pointer;
            font-size: 1em;
        }
        
        .btn:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn.secondary {
            background: white;
            color: #667eea;
            border: 2px solid #667eea;
        }
        
        .comparison-table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        
        .comparison-table th,
        .comparison-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        
        .comparison-table th {
            background: #667eea;
            color: white;
            font-weight: bold;
        }
        
        .comparison-table tr:hover {
            background: #f5f5f5;
        }
        
        .category-header {
            background: #f0f0f0;
            font-weight: bold;
            color: #667eea;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ '📊 Test Results' if test_type == 'bulk' else '🎯 Single Image Results' }}</h1>
        <div class="summary">
            <p><strong>Test completed at:</strong> {{ timestamp }}</p>
            {% if test_type == 'bulk' %}
            <p><strong>Success rate:</strong> {{ successful }}/{{ total }} images ({{ success_rate }}%)</p>
            {% endif %}
        </div>
        
        {% if test_type == 'bulk' %}
            {% for category in categories %}
            <h2 style="color: #667eea; margin: 30px 0 15px 0;">{{ category }}</h2>
            
            {% for result in results_by_category[category] %}
            <div class="result-card {% if 'error' in result %}error{% endif %}">
                <div class="result-header">
                    <h2>{{ result.description or result.image }}</h2>
                    <span class="badge {% if 'error' in result %}error{% else %}success{% endif %}">
                        {% if 'error' in result %}Failed{% else %}Success{% endif %}
                    </span>
                </div>
                
                {% if 'error' not in result %}
                <div class="metrics">
                    <div class="metric">
                        <div class="metric-label">Avg CPU</div>
                        <div class="metric-value">{{ result.cpu_avg }}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Peak CPU</div>
                        <div class="metric-value">{{ result.cpu_peak }}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Avg Memory</div>
                        <div class="metric-value">{{ format_memory(result.mem_avg_mb) }}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Peak Memory</div>
                        <div class="metric-value">{{ format_memory(result.mem_peak_mb) }}</div>
                    </div>
                </div>
                
                <div class="recommendation">
                    <h3>☁️ Recommended Cloud Instances</h3>
                    <p style="margin-bottom: 15px;">
                        <strong>{{ result.recommendation.vcpu }} vCPU(s), {{ result.recommendation.ram_gb }} GB RAM</strong>
                    </p>
                    <div class="instances">
                        <div class="instance">
                            <div class="instance-provider">AWS</div>
                            <div class="instance-type">{{ result.instances.aws }}</div>
                        </div>
                        <div class="instance">
                            <div class="instance-provider">Google Cloud</div>
                            <div class="instance-type">{{ result.instances.gcp }}</div>
                        </div>
                        <div class="instance">
                            <div class="instance-provider">Azure</div>
                            <div class="instance-type">{{ result.instances.azure }}</div>
                        </div>
                    </div>
                </div>
                {% else %}
                <p style="color: #ef4444; font-weight: bold;">❌ Error: {{ result.error }}</p>
                {% endif %}
            </div>
            {% endfor %}
            {% endfor %}
        
        {% else %}
            {% if 'error' not in results[0] %}
            <div class="result-card">
                <div class="result-header">
                    <h2>{{ results[0].image }}</h2>
                    <span class="badge success">Success</span>
                </div>
                
                <div class="metrics">
                    <div class="metric">
                        <div class="metric-label">Avg CPU</div>
                        <div class="metric-value">{{ results[0].cpu_avg }}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Peak CPU</div>
                        <div class="metric-value">{{ results[0].cpu_peak }}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Avg Memory</div>
                        <div class="metric-value">{{ format_memory(results[0].mem_avg_mb) }}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Peak Memory</div>
                        <div class="metric-value">{{ format_memory(results[0].mem_peak_mb) }}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Samples Collected</div>
                        <div class="metric-value">{{ results[0].samples }}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Test Duration</div>
                        <div class="metric-value">{{ results[0].duration_sec }}s</div>
                    </div>
                </div>
                
                <div class="recommendation">
                    <h3>☁️ Recommended Cloud Instances</h3>
                    <p style="margin-bottom: 15px;">
                        <strong>{{ results[0].recommendation.vcpu }} vCPU(s), {{ results[0].recommendation.ram_gb }} GB RAM</strong>
                    </p>
                    <div class="instances">
                        <div class="instance">
                            <div class="instance-provider">AWS</div>
                            <div class="instance-type">{{ results[0].instances.aws }}</div>
                        </div>
                        <div class="instance">
                            <div class="instance-provider">Google Cloud</div>
                            <div class="instance-type">{{ results[0].instances.gcp }}</div>
                        </div>
                        <div class="instance">
                            <div class="instance-provider">Azure</div>
                            <div class="instance-type">{{ results[0].instances.azure }}</div>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="result-card error">
                <div class="result-header">
                    <h2>{{ results[0].image or 'Test Failed' }}</h2>
                    <span class="badge error">Error</span>
                </div>
                <p style="color: #ef4444; font-weight: bold; font-size: 1.1em;">
                    ❌ {{ results[0].error }}
                </p>
            </div>
            {% endif %}
        {% endif %}
        
        <div class="actions">
            <a href="/" class="btn">🏠 Back to Home</a>
            <a href="/bulk-test" class="btn secondary">📊 New Bulk Test</a>
            <a href="/single-test" class="btn secondary">🎯 New Single Test</a>
        </div>
    </div>
</body>
</html>
"""


# Routes
@app.route('/')
def home():
    return render_template_string(HOME_TEMPLATE)


@app.route('/bulk-test')
def bulk_test():
    return render_template_string(BULK_TEST_TEMPLATE)


@app.route('/single-test')
def single_test():
    return render_template_string(SINGLE_TEST_TEMPLATE)


@app.route('/live-test')
def live_test():
    return render_template_string(LIVE_TEST_TEMPLATE)


@app.route('/api/start-bulk-test', methods=['POST'])
def api_start_bulk_test():
    data = request.json
    duration = data.get('duration', 20)
    
    # Start tests in background thread
    thread = threading.Thread(target=run_bulk_tests, args=(duration,))
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'started'})


@app.route('/api/bulk-test-progress')
def api_bulk_test_progress():
    return jsonify(test_progress)


@app.route('/api/start-single-test', methods=['POST'])
def api_start_single_test():
    data = request.json
    image = data.get('image')
    duration = data.get('duration', 30)
    command = data.get('command')
    
    result = estimate_single_image(image, duration, command)
    
    # Store in session
    session['single_test_result'] = result
    
    if 'error' in result:
        return jsonify({'status': 'error', 'error': result['error']})
    
    return jsonify({'status': 'success'})


@app.route('/api/start-live-test', methods=['POST'])
def api_start_live_test():
    """Start a container for live monitoring."""
    global live_containers
    
    data = request.json
    image_name = data.get('image')
    custom_command = data.get('command')
    port_mapping = data.get('port_mapping')
    
    try:
        client = docker.from_env()
        
        # Check/pull image
        try:
            image = client.images.get(image_name)
        except docker.errors.ImageNotFound:
            try:
                image = client.images.pull(image_name)
            except docker.errors.APIError as e:
                return jsonify({'status': 'error', 'error': f'Failed to pull image: {str(e)}'})
        
        # Parse port mapping
        ports = None
        port_info = None
        if port_mapping:
            try:
                host_port, container_port = port_mapping.split(':')
                # Bind to all interfaces (0.0.0.0) to ensure accessibility
                ports = {f'{container_port}/tcp': ('0.0.0.0', int(host_port))}
                port_info = f'(Port {host_port} → {container_port})'
            except:
                return jsonify({'status': 'error', 'error': 'Invalid port mapping format. Use host_port:container_port'})
        
        # Start container with proper flags
        container = None
        try:
            # Use stdin_open and tty for interactive containers (like MobSF)
            # Set network_mode to bridge for proper port exposure
            container_args = {
                'detach': True,
                'stdin_open': True,
                'tty': True,
                'ports': ports,
                'network_mode': 'bridge'
            }
            
            # Only add command if specified, let container use default CMD otherwise
            if custom_command:
                container_args['command'] = custom_command
            
            container = client.containers.run(image_name, **container_args)
        except docker.errors.APIError as e:
            # Try fallback commands only if custom command wasn't specified
            if "executable file not found" in str(e) and not custom_command:
                try:
                    container_args['command'] = "sleep infinity"
                    container = client.containers.run(image_name, **container_args)
                except:
                    try:
                        # Try without any command
                        container_args.pop('command', None)
                        container = client.containers.run(image_name, **container_args)
                    except Exception as final_e:
                        return jsonify({'status': 'error', 'error': f'Failed to start container: {str(final_e)}'})
            else:
                return jsonify({'status': 'error', 'error': f'Failed to start container: {str(e)}'})
        
        # Wait a moment for container to fully start
        time.sleep(2)
        
        # Verify container is running and get port info
        try:
            container.reload()
            if container.status != 'running':
                return jsonify({'status': 'error', 'error': f'Container started but not running. Status: {container.status}'})
            
            # Get actual port bindings
            port_bindings = container.attrs.get('NetworkSettings', {}).get('Ports', {})
            if ports and port_bindings:
                port_info_detailed = f'{port_info} - Access at http://localhost:{host_port}'
            else:
                port_info_detailed = port_info
        except Exception as e:
            port_info_detailed = port_info
        
        # Store container info
        container_id = container.id
        live_containers[container_id] = {
            'container': container,
            'image': image_name,
            'start_time': time.time(),
            'cpu_history': [],
            'mem_history': [],
            'samples': 0,
            'logs': ''
        }
        
        return jsonify({
            'status': 'success',
            'container_id': container_id,
            'port_info': port_info_detailed
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


@app.route('/api/live-test-stats')
def api_live_test_stats():
    """Get current stats for a running container."""
    global live_containers
    
    container_id = request.args.get('container_id')
    
    if container_id not in live_containers:
        return jsonify({'status': 'error', 'error': 'Container not found'})
    
    container_info = live_containers[container_id]
    container = container_info['container']
    
    try:
        # Check if container is still running
        container.reload()
        if container.status != 'running':
            return jsonify({'status': 'error', 'error': 'Container is not running'})
        
        # Get stats (non-streaming)
        stats = container.stats(stream=False)
        
        # CPU calculation
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        
        cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        precpu_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        
        system_cpu = cpu_stats.get("system_cpu_usage", 0)
        presystem_cpu = precpu_stats.get("system_cpu_usage", 0)
        
        cpu_delta = cpu_total - precpu_total
        system_delta = system_cpu - presystem_cpu
        
        online_cpus = cpu_stats.get("online_cpus")
        if not online_cpus:
            percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
            online_cpus = len(percpu_usage) if percpu_usage else 1
        
        cpu_percent = 0
        if system_delta > 0 and cpu_delta >= 0:
            cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
        
        # Memory
        mem_usage = stats.get("memory_stats", {}).get("usage", 0) / (1024 ** 2)
        
        # Update history
        container_info['cpu_history'].append(cpu_percent)
        container_info['mem_history'].append(mem_usage)
        container_info['samples'] += 1
        
        # Calculate stats
        cpu_avg = statistics.mean(container_info['cpu_history']) if container_info['cpu_history'] else 0
        cpu_peak = max(container_info['cpu_history']) if container_info['cpu_history'] else 0
        mem_avg = statistics.mean(container_info['mem_history']) if container_info['mem_history'] else 0
        mem_peak = max(container_info['mem_history']) if container_info['mem_history'] else 0
        
        # Get container logs (last 500 lines to avoid overload)
        try:
            logs = container.logs(tail=500).decode('utf-8', errors='replace')
            container_info['logs'] = logs
        except:
            logs = container_info['logs']
        
        return jsonify({
            'status': 'success',
            'cpu_current': cpu_percent,
            'cpu_avg': cpu_avg,
            'cpu_peak': cpu_peak,
            'mem_current': mem_usage,
            'mem_avg': mem_avg,
            'mem_peak': mem_peak,
            'samples': container_info['samples'],
            'runtime': time.time() - container_info['start_time'],
            'logs': logs
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


@app.route('/api/stop-live-test', methods=['POST'])
def api_stop_live_test():
    """Stop and remove a live test container."""
    global live_containers
    
    data = request.json
    container_id = data.get('container_id')
    
    if container_id not in live_containers:
        return jsonify({'status': 'error', 'error': 'Container not found'})
    
    container_info = live_containers[container_id]
    container = container_info['container']
    
    try:
        # Calculate recommendations before stopping
        cpu_history = container_info['cpu_history']
        mem_history = container_info['mem_history']
        
        recommendations = None
        if cpu_history and mem_history:
            cpu_avg = statistics.mean(cpu_history)
            cpu_peak = max(cpu_history)
            mem_avg = statistics.mean(mem_history)
            mem_peak = max(mem_history)
            
            # Calculate recommended resources
            recommended_vcpu = max(1, round(cpu_peak / 80))
            recommended_ram = round(mem_peak * 1.5 / 1024, 2)
            
            # Get instance recommendations
            instances = get_instance_recommendations(recommended_vcpu, recommended_ram)
            
            recommendations = {
                'vcpu': recommended_vcpu,
                'ram_gb': recommended_ram,
                'instances': instances,
                'stats': {
                    'cpu_avg': round(cpu_avg, 2),
                    'cpu_peak': round(cpu_peak, 2),
                    'mem_avg_mb': round(mem_avg, 2),
                    'mem_peak_mb': round(mem_peak, 2),
                    'samples': container_info['samples'],
                    'duration_sec': round(time.time() - container_info['start_time'])
                }
            }
        
        container.stop()
        container.remove()
        del live_containers[container_id]
        
        return jsonify({
            'status': 'success',
            'recommendations': recommendations
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})


@app.route('/results')
def results():
    test_type = request.args.get('type', 'single')
    
    if test_type == 'bulk':
        results = test_progress['results']
        
        # Group by category
        categories = []
        results_by_category = {}
        for result in results:
            if 'error' not in result:
                category = result.get('category', 'Other')
                if category not in categories:
                    categories.append(category)
                    results_by_category[category] = []
                results_by_category[category].append(result)
        
        successful = len([r for r in results if 'error' not in r])
        total = len(results)
        success_rate = round((successful / total) * 100) if total > 0 else 0
        
        return render_template_string(
            RESULTS_TEMPLATE,
            test_type=test_type,
            results=results,
            categories=categories,
            results_by_category=results_by_category,
            successful=successful,
            total=total,
            success_rate=success_rate,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            format_memory=lambda mb: f"{mb:.2f} MB" if mb >= 1 else f"{mb*1024:.2f} KB"
        )
    else:
        result = session.get('single_test_result', {})
        return render_template_string(
            RESULTS_TEMPLATE,
            test_type=test_type,
            results=[result],
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            format_memory=lambda mb: f"{mb:.2f} MB" if mb >= 1 else f"{mb*1024:.2f} KB"
        )


if __name__ == '__main__':
    print("=" * 80)
    print("🐳 Docker Resource Estimator - Web Application")
    print("=" * 80)
    print("\n📡 Server starting...")
    print("🌐 Access the app at: http://localhost:5000")
    print("\n💡 Features:")
    print("   • Bulk test all 10 default Docker images")
    print("   • Test custom Docker images")
    print("   • Get AWS, GCP, and Azure instance recommendations")
    print("\n⏹️  Press Ctrl+C to stop the server\n")
    print("=" * 80)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
