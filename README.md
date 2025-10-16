# Docker Resource Estimator 🐳

A Python tool that profiles Docker container resource usage and provides cloud instance recommendations for AWS, GCP, and Azure.

## Features ✨

- **Automated Resource Profiling**: Monitors CPU and memory usage of Docker containers
- **Cloud Instance Recommendations**: Suggests appropriate instance types for major cloud providers
- **Flexible Usage**: Interactive mode or CLI with arguments
- **Smart Fallbacks**: Automatically handles images with different base systems
- **Detailed Reports**: Generates JSON reports with comprehensive metrics

## Prerequisites 📋

### Required Software
- **Docker Desktop** (running and accessible)
- **Python 3.7+**
- **docker-py library**

### Installation

1. **Install Docker Desktop**
   - Download from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
   - Ensure Docker Engine is running

2. **Install Python Dependencies**
   ```powershell
   pip install docker
   ```

3. **Verify Docker is Running**
   ```powershell
   docker --version
   docker ps
   ```

## Usage 🚀

### Interactive Mode

Run without arguments for interactive prompts:

```powershell
python docker_resource_estimator.py
```

You'll be prompted to enter:
1. Docker image name (e.g., `nginx:latest`)
2. Test duration in seconds (default: 30)
3. Custom command (optional)

### CLI Mode (Recommended)

Use command-line arguments for automation:

```powershell
# Basic usage
python docker_resource_estimator.py --image nginx:latest --duration 30

# With custom command
python docker_resource_estimator.py --image redis:latest --duration 60 --command "redis-server"

# Short form
python docker_resource_estimator.py -i alpine:latest -d 20
```

### Command-Line Arguments

| Argument | Short | Description | Example |
|----------|-------|-------------|---------|
| `--image` | `-i` | Docker image name | `nginx:latest` |
| `--duration` | `-d` | Test duration in seconds | `30` |
| `--command` | `-c` | Custom container command | `redis-server` |
| `--stop-docker` | `-s` | Stop Docker Engine after completion | (flag, no value) |
| `--help` | `-h` | Show help message | - |

## Example Commands 📝

### Basic Usage

```powershell
# Standard test (Docker stays running)
python docker_resource_estimator.py --image nginx:latest --duration 30

# Test and stop Docker Engine when done
python docker_resource_estimator.py --image nginx:latest --duration 30 --stop-docker
```

### Web Servers

```powershell
# Nginx
python docker_resource_estimator.py --image nginx:latest --duration 30

# Apache
python docker_resource_estimator.py --image httpd:latest --duration 30
```

### Databases

```powershell
# Redis
python docker_resource_estimator.py --image redis:latest --duration 60 --command "redis-server"

# PostgreSQL
python docker_resource_estimator.py --image postgres:latest --duration 60

# MySQL
python docker_resource_estimator.py --image mysql:latest --duration 60
```

### Programming Languages

```powershell
# Python
python docker_resource_estimator.py --image python:3.11 --duration 30

# Node.js
python docker_resource_estimator.py --image node:18 --duration 30

# Java
python docker_resource_estimator.py --image openjdk:17 --duration 30
```

### Minimal/Test Images

```powershell
# Alpine Linux
python docker_resource_estimator.py --image alpine:latest --duration 20

# Ubuntu
python docker_resource_estimator.py --image ubuntu:latest --duration 20

# BusyBox
python docker_resource_estimator.py --image busybox:latest --duration 20 --command "sleep 300"
```

## Output 📊

### Console Output

The script provides a detailed summary:

```
=== Docker Resource Estimator ===

🔍 Checking if image 'nginx:latest' is available locally...
✅ Image found locally.

🚀 Running container from 'nginx:latest' for 30s...
✅ Container started with command: tail -f /dev/null
🧹 Cleaning up container...

📊 === Resource Summary ===
Average CPU: 0.15%
Peak CPU: 0.45%
Average Memory: 2.34 MB
Peak Memory: 3.12 MB

☁️ === Cloud Estimate ===
Suggested: 1 vCPU(s), 0.01 GB RAM

💡 Recommended Instances:
• AWS: t3.micro / GCP: e2-micro / Azure: B1s

📁 Report saved as resource_report.json
```

### JSON Report

A detailed report is saved to `resource_report.json`:

```json
{
    "image": "nginx:latest",
    "duration_sec": 30,
    "cpu_avg": 0.15,
    "cpu_peak": 0.45,
    "mem_avg_mb": 2.34,
    "mem_peak_mb": 3.12,
    "recommendation": {
        "vcpu": 1,
        "ram_gb": 0.01
    }
}
```

## Cloud Instance Mapping 🌩️

| vCPU | RAM | AWS | GCP | Azure |
|------|-----|-----|-----|-------|
| 1 | ≤ 1 GB | t3.micro | e2-micro | B1s |
| 1 | ≤ 2 GB | t3.small | e2-small | B1ms |
| 2 | Any | t3.medium | e2-medium | B2s |
| 2+ | Any | t3.large+ | e2-standard | B2ms+ |

## Troubleshooting 🔧

### Docker Not Running

**Error:** `Error while fetching server API version`

**Solution:**
```powershell
# Start Docker Desktop
# Wait for Docker Engine to start
docker ps
```

### Image Not Found

**Error:** `Failed to pull image`

**Solution:**
```powershell
# Manually pull the image
docker pull nginx:latest

# Then run the estimator
python docker_resource_estimator.py --image nginx:latest --duration 30
```

### Permission Denied (Linux/Mac)

**Error:** `Permission denied while trying to connect to Docker`

**Solution:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and log back in
```

### "No stats collected" Error

**Causes:**
- Container exits too quickly (e.g., `hello-world`)
- Test duration too short
- Container command fails

**Solutions:**
```powershell
# Increase duration
python docker_resource_estimator.py --image yourimage:tag --duration 60

# Use a custom command that keeps container alive
python docker_resource_estimator.py --image yourimage:tag --duration 30 --command "sleep infinity"

# Try a different base image
python docker_resource_estimator.py --image alpine:latest --duration 30
```

### Executable Not Found in $PATH

**Error:** `exec: "tail": executable file not found in $PATH`

**Solution:**
The script automatically tries fallback commands. If it still fails, specify a custom command:

```powershell
# For Windows-based containers
python docker_resource_estimator.py --image yourimage:tag --command "ping localhost -t"

# For minimal images
python docker_resource_estimator.py --image yourimage:tag --command "sleep 300"

# Use the default command
python docker_resource_estimator.py --image yourimage:tag --command ""
```

## How It Works ⚙️

1. **Image Check**: Verifies image exists locally or pulls from registry
2. **Container Launch**: Starts container with keep-alive command
3. **Stats Collection**: Streams CPU and memory metrics every second
4. **Analysis**: Calculates averages and peaks using delta-based CPU calculation
5. **Recommendations**: Suggests vCPU and RAM based on peak usage with safety margins
6. **Cleanup**: Stops and removes container automatically
7. **Report Generation**: Saves detailed metrics to JSON

## CPU Calculation Method

The tool uses Docker's recommended delta-based calculation:

```python
cpu_delta = current_cpu_usage - previous_cpu_usage
system_delta = current_system_cpu - previous_system_cpu
cpu_percent = (cpu_delta / system_delta) * number_of_cpus * 100
```

This provides accurate CPU usage percentages across different systems.

## Known Limitations ⚠️

- **hello-world image**: Not supported (exits immediately by design)
- **Windows containers**: May require different keep-alive commands
- **Interactive containers**: Won't work with containers requiring user input
- **Short-lived tasks**: Need sufficient test duration to collect meaningful data

## Best Practices 💡

1. **Test Duration**: Use at least 30 seconds for meaningful data
2. **Realistic Workloads**: Use commands that simulate actual usage
3. **Multiple Runs**: Run tests multiple times and average results
4. **Load Testing**: For production estimates, test under simulated load
5. **Safety Margins**: The tool adds 50% RAM buffer; adjust based on your needs
6. **Docker Engine Management**: 
   - Use `--stop-docker` flag if you want to save system resources after testing
   - Leave Docker running if you plan to do more Docker work (faster than restarting)
   - Docker Engine uses minimal resources when idle

## Automated Testing

Use the included test runner to test multiple images:

```powershell
python test_runner.py
```

See `test_runner.py` for details.

## License

MIT License - Feel free to use and modify

## Contributing

Issues and pull requests welcome!

---

**Made with ❤️ for cloud infrastructure planning**
