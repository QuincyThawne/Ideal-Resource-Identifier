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
