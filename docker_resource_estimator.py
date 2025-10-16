import docker
import time
import statistics
import json
import sys
import argparse
import io
import subprocess
import platform

# Fix encoding for Windows PowerShell
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def stop_docker_engine():
    """Stop Docker Engine/Desktop after execution."""
    system = platform.system()
    
    print("\n🛑 Stopping Docker Engine...")
    
    try:
        if system == "Windows":
            # Stop Docker Desktop on Windows
            subprocess.run(
                ["powershell", "-Command", "Stop-Process -Name 'Docker Desktop' -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                timeout=10
            )
            print("✅ Docker Desktop stopped successfully")
        elif system == "Linux":
            # Stop Docker service on Linux
            subprocess.run(
                ["sudo", "systemctl", "stop", "docker"],
                capture_output=True,
                timeout=10
            )
            print("✅ Docker service stopped successfully")
        elif system == "Darwin":  # macOS
            # Stop Docker Desktop on macOS
            subprocess.run(
                ["osascript", "-e", 'quit app "Docker"'],
                capture_output=True,
                timeout=10
            )
            print("✅ Docker Desktop stopped successfully")
        else:
            print(f"⚠️  Automatic Docker shutdown not supported on {system}")
            print("   Please stop Docker manually if needed")
    except subprocess.TimeoutExpired:
        print("⚠️  Docker shutdown timed out")
    except Exception as e:
        print(f"⚠️  Could not stop Docker Engine: {e}")
        print("   You may need to stop it manually")

def estimate_resources(image_name: str, test_duration: int = 30, custom_command: str = None, stop_docker: bool = False):
    client = docker.from_env()

    print(f"\n🔍 Checking if image '{image_name}' is available locally...")
    try:
        image = client.images.get(image_name)
        print("✅ Image found locally.")
    except docker.errors.ImageNotFound:
        print("⬇️  Image not found locally. Pulling from registry...")
        try:
            image = client.images.pull(image_name)
            print("✅ Image pulled successfully.")
        except docker.errors.APIError as e:
            print(f"❌ Failed to pull image: {e}")
            sys.exit(1)

    print(f"\n🚀 Running container from '{image_name}' for {test_duration}s...")
    container = None
    try:
        # Use custom command if provided, otherwise use tail -f /dev/null to keep container alive
        if custom_command:
            cmd = custom_command  # Can be string or list
        else:
            # Try different commands in order of preference
            cmd = "tail -f /dev/null"
        
        container = client.containers.run(image_name, detach=True, command=cmd)
        cmd_display = cmd if isinstance(cmd, str) else ' '.join(cmd)
        print(f"✅ Container started with command: {cmd_display}")
    except docker.errors.ContainerError as e:
        print(f"❌ Failed to run container: {e}")
        sys.exit(1)
    except docker.errors.APIError as e:
        # If tail command failed, try alternative commands
        if "executable file not found" in str(e) and not custom_command:
            print(f"⚠️  'tail' command not found in image. Trying alternative commands...")
            
            # Try sleep infinity
            try:
                container = client.containers.run(image_name, detach=True, command="sleep infinity")
                print(f"✅ Container started with command: sleep infinity")
            except docker.errors.APIError:
                # Try sh -c sleep
                try:
                    container = client.containers.run(image_name, detach=True, command=["/bin/sh", "-c", "sleep infinity"])
                    print(f"✅ Container started with command: /bin/sh -c sleep infinity")
                except docker.errors.APIError:
                    # Last resort: use image's default command
                    try:
                        container = client.containers.run(image_name, detach=True)
                        print(f"⚠️  Using image's default command (may exit quickly)")
                    except docker.errors.APIError as final_e:
                        print(f"❌ Docker API error: {final_e}")
                        sys.exit(1)
        else:
            print(f"❌ Docker API error: {e}")
            sys.exit(1)

    cpu_usages = []
    mem_usages = []
    previous_cpu = 0
    previous_system = 0

    try:
        stats_stream = container.stats(stream=True)
        start = time.time()
        sample_count = 0
        while time.time() - start < test_duration:
            try:
                # Check if container is still running
                container.reload()
                if container.status != 'running':
                    print(f"\n⚠️  Container exited with status '{container.status}' after {sample_count} samples.")
                    print(f"💡 Tip: This image may need a custom command to stay running.")
                    break
                
                stats_raw = next(stats_stream)
                
                # Decode stats if it's bytes
                if isinstance(stats_raw, bytes):
                    stats = json.loads(stats_raw.decode('utf-8'))
                else:
                    stats = stats_raw
                
                # Correct CPU calculation using deltas
                cpu_stats = stats.get("cpu_stats", {})
                precpu_stats = stats.get("precpu_stats", {})
                
                cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                precpu_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                
                system_cpu = cpu_stats.get("system_cpu_usage", 0)
                presystem_cpu = precpu_stats.get("system_cpu_usage", 0)
                
                # Calculate deltas
                cpu_delta = cpu_total - precpu_total
                system_delta = system_cpu - presystem_cpu
                
                # Get number of CPUs
                online_cpus = cpu_stats.get("online_cpus")
                if not online_cpus:
                    percpu_usage = cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])
                    online_cpus = len(percpu_usage) if percpu_usage else 1
                
                # Calculate CPU percentage
                if system_delta > 0 and cpu_delta >= 0:
                    cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                    cpu_usages.append(cpu_percent)
                
                # Memory calculation
                mem_usage = stats.get("memory_stats", {}).get("usage", 0) / (1024 ** 2)
                mem_usages.append(mem_usage)
                
                sample_count += 1
                time.sleep(1)
            except (StopIteration, KeyError) as e:
                # Container exited or stats unavailable
                print(f"\n⚠️  Container exited or stats unavailable after {sample_count} samples.")
                break
    except KeyboardInterrupt:
        print("\n⏹️  Interrupted by user. Stopping container early.")
    except Exception as e:
        print(f"\n⚠️  Error during stats collection: {e}")
    finally:
        if container:
            print("🧹 Cleaning up container...")
            try:
                container.stop()
                container.remove()
            except Exception as e:
                print(f"⚠️  Error during cleanup: {e}")

    if not cpu_usages or not mem_usages:
        print("❌ No stats collected. The container might have exited too early.")
        sys.exit(1)

    avg_cpu = statistics.mean(cpu_usages)
    peak_cpu = max(cpu_usages)
    avg_mem = statistics.mean(mem_usages)
    peak_mem = max(mem_usages)

    recommended_vcpu = max(1, round(peak_cpu / 80))
    recommended_ram = round(peak_mem * 1.5 / 1024, 2)  # GB

    print("\n📊 === Resource Summary ===")
    print(f"Average CPU: {avg_cpu:.2f}%")
    print(f"Peak CPU: {peak_cpu:.2f}%")
    print(f"Average Memory: {avg_mem:.2f} MB")
    print(f"Peak Memory: {peak_mem:.2f} MB")

    print("\n☁️ === Cloud Estimate ===")
    print(f"Suggested: {recommended_vcpu} vCPU(s), {recommended_ram} GB RAM")

    print("\n💡 Recommended Instances:")
    if recommended_vcpu == 1 and recommended_ram <= 1:
        print("• AWS: t3.micro / GCP: e2-micro / Azure: B1s")
    elif recommended_vcpu == 1 and recommended_ram <= 2:
        print("• AWS: t3.small / GCP: e2-small / Azure: B1ms")
    elif recommended_vcpu == 2:
        print("• AWS: t3.medium / GCP: e2-medium / Azure: B2s")
    else:
        print("• AWS: t3.large+ / GCP: e2-standard / Azure: B2ms+")

    result = {
        "image": image_name,
        "duration_sec": test_duration,
        "cpu_avg": avg_cpu,
        "cpu_peak": peak_cpu,
        "mem_avg_mb": avg_mem,
        "mem_peak_mb": peak_mem,
        "recommendation": {
            "vcpu": recommended_vcpu,
            "ram_gb": recommended_ram
        }
    }

    with open("resource_report.json", "w") as f:
        json.dump(result, f, indent=4)
    print("\n📁 Report saved as resource_report.json")
    
    # Stop Docker Engine if requested
    if stop_docker:
        stop_docker_engine()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Docker Resource Estimator - Profile container resource usage and get cloud instance recommendations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode:
    python docker_resource_estimator.py
  
  CLI mode:
    python docker_resource_estimator.py --image nginx:latest --duration 60
    python docker_resource_estimator.py --image redis:latest --duration 45 --command "redis-server"
        """
    )
    
    parser.add_argument('--image', '-i', type=str, help='Docker image name (e.g., nginx:latest)')
    parser.add_argument('--duration', '-d', type=int, help='Test duration in seconds (default: 30)')
    parser.add_argument('--command', '-c', type=str, help='Custom command to run in container (default: tail -f /dev/null)')
    parser.add_argument('--stop-docker', '-s', action='store_true', help='Stop Docker Engine after execution completes')
    
    args = parser.parse_args()
    
    print("=== Docker Resource Estimator ===")
    
    # Use CLI args if provided, otherwise prompt interactively
    if args.image:
        image = args.image
        duration = args.duration if args.duration else 30
        custom_cmd = args.command
        stop_docker_flag = args.stop_docker
    else:
        image = input("Enter Docker image name (e.g. nginx:latest): ").strip()
        duration = input("Enter test duration in seconds [default=30]: ").strip()
        duration = int(duration) if duration.isdigit() else 30
        use_custom = input("Use custom command? (leave empty for default 'tail -f /dev/null'): ").strip()
        custom_cmd = use_custom if use_custom else None
        stop_docker_input = input("Stop Docker Engine after completion? (y/n) [default=n]: ").strip().lower()
        stop_docker_flag = stop_docker_input == 'y'
    
    estimate_resources(image, duration, custom_cmd, stop_docker_flag)
