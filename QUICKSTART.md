# Quick Start Guide

## Installation

```powershell
# Install Docker Python library
pip install docker
```

## Basic Usage

### Single Image Test
```powershell
# Test nginx for 30 seconds
python docker_resource_estimator.py --image nginx:latest --duration 30

# Test and stop Docker when done
python docker_resource_estimator.py --image nginx:latest --duration 30 --stop-docker
```

### Quick Automated Tests (4 images)
```powershell
# Run quick test suite
python test_runner.py --quick --duration 15
```

### Full Automated Tests (10 images)
```powershell
# Run full test suite
python test_runner.py --duration 30
```

### Test Specific Image from Suite
```powershell
# Test only nginx from the suite
python test_runner.py --image nginx:latest --duration 20
```

## Common Commands

| Command | Description |
|---------|-------------|
| `python docker_resource_estimator.py` | Interactive mode |
| `python docker_resource_estimator.py -i nginx:latest -d 30` | Test nginx for 30s |
| `python docker_resource_estimator.py -i nginx:latest -d 30 -s` | Test and stop Docker |
| `python test_runner.py -q` | Quick test (4 images) |
| `python test_runner.py -d 60` | Full test with 60s per image |
| `python test_runner.py --help` | Show all options |

## Output Files

- `resource_report.json` - Latest single test result
- `test_results_YYYYMMDD_HHMMSS.json` - Full test suite results with timestamp

## Recommended Test Images

✅ **Works well:**
- `nginx:latest` - Web server
- `redis:latest` - Database
- `python:3.11` - Language runtime
- `alpine:latest` - Minimal OS

❌ **Not suitable:**
- `hello-world` - Exits immediately
- Images that require user interaction
- Images that exit on startup

## Troubleshooting

**Problem:** "No stats collected"
**Solution:** Increase duration: `--duration 60`

**Problem:** Docker not running
**Solution:** Start Docker Desktop

**Problem:** Image not found
**Solution:** Docker will automatically pull it, or pull manually: `docker pull nginx:latest`

## Example Output

```
📊 === Resource Summary ===
Average CPU: 0.15%
Peak CPU: 0.45%
Average Memory: 2.34 MB
Peak Memory: 3.12 MB

☁️ === Cloud Estimate ===
Suggested: 1 vCPU(s), 0.01 GB RAM

💡 Recommended Instances:
• AWS: t3.micro / GCP: e2-micro / Azure: B1s
```
