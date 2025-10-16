"""
Docker Resource Estimator - Automated Test Runner

This script automatically tests multiple Docker images and generates
a comprehensive comparison report.

Usage:
    python test_runner.py
    python test_runner.py --duration 60
    python test_runner.py --quick
"""

import subprocess
import json
import sys
import time
from datetime import datetime
import argparse

# Test configurations: (image_name, custom_command, description)
TEST_IMAGES = [
    {
        "name": "nginx:latest",
        "command": "nginx -g 'daemon off;'",
        "description": "Nginx Web Server",
        "category": "Web Servers"
    },
    {
        "name": "httpd:latest",
        "command": "httpd-foreground",
        "description": "Apache HTTP Server",
        "category": "Web Servers"
    },
    {
        "name": "redis:latest",
        "command": "redis-server",
        "description": "Redis Cache",
        "category": "Databases"
    },
    {
        "name": "postgres:latest",
        "command": None,  # Postgres exits without POSTGRES_PASSWORD, use tail fallback
        "description": "PostgreSQL Database",
        "category": "Databases",
        "startup_delay": 5,  # Extra time for DB initialization
        "needs_env": True  # Flag that this needs environment variables
    },
    {
        "name": "mysql:latest",
        "command": None,  # MySQL requires env vars, use default tail -f /dev/null
        "description": "MySQL Database",
        "category": "Databases"
    },
    {
        "name": "python:3.11",
        "command": "sleep 3600",
        "description": "Python 3.11",
        "category": "Languages"
    },
    {
        "name": "node:18",
        "command": "sleep 3600",
        "description": "Node.js 18",
        "category": "Languages"
    },
    {
        "name": "openjdk:17",
        "command": "jshell",
        "description": "OpenJDK 17",
        "category": "Languages"
    },
    {
        "name": "alpine:latest",
        "command": None,
        "description": "Alpine Linux (Minimal)",
        "category": "Base Images"
    },
    {
        "name": "ubuntu:latest",
        "command": None,
        "description": "Ubuntu Linux",
        "category": "Base Images"
    },
]

# Quick test subset (for faster testing)
QUICK_TEST_IMAGES = [
    {
        "name": "nginx:latest",
        "command": "nginx -g 'daemon off;'",
        "description": "Nginx Web Server",
        "category": "Web Servers"
    },
    {
        "name": "redis:latest",
        "command": "redis-server",
        "description": "Redis Cache",
        "category": "Databases"
    },
    {
        "name": "python:3.11",
        "command": "sleep 3600",
        "description": "Python 3.11",
        "category": "Languages"
    },
    {
        "name": "alpine:latest",
        "command": None,
        "description": "Alpine Linux (Minimal)",
        "category": "Base Images"
    },
]


def run_estimation(image_name, duration, custom_command=None, startup_delay=0):
    """Run resource estimation for a single image."""
    cmd = [
        sys.executable,
        "docker_resource_estimator.py",
        "--image", image_name,
        "--duration", str(duration)
    ]
    
    if custom_command:
        cmd.extend(["--command", custom_command])
    
    # Calculate timeout with startup delay buffer
    timeout = duration + 30 + startup_delay
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',  # Ignore encoding errors from Docker output
            timeout=timeout  # Extended timeout for slow-starting containers
        )
        
        if result.returncode == 0:
            # Read the generated report
            try:
                with open("resource_report.json", "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {"error": "Report file not found"}
        else:
            return {
                "error": result.stderr or "Process failed",
                "returncode": result.returncode
            }
    except subprocess.TimeoutExpired:
        return {"error": "Test timed out"}
    except Exception as e:
        return {"error": str(e)}


def format_size(mb):
    """Format memory size."""
    if mb < 1:
        return f"{mb * 1024:.2f} KB"
    elif mb < 1024:
        return f"{mb:.2f} MB"
    else:
        return f"{mb / 1024:.2f} GB"


def print_separator():
    """Print a visual separator."""
    print("=" * 80)


def print_result(image_config, result, index, total):
    """Print individual test result."""
    print(f"\n[{index}/{total}] Testing: {image_config['description']}")
    print(f"Image: {image_config['name']}")
    
    if "error" in result:
        print(f"❌ FAILED: {result['error']}")
        return False
    
    print(f"✅ SUCCESS")
    print(f"   CPU  - Avg: {result['cpu_avg']:.2f}% | Peak: {result['cpu_peak']:.2f}%")
    print(f"   RAM  - Avg: {format_size(result['mem_avg_mb'])} | Peak: {format_size(result['mem_peak_mb'])}")
    print(f"   Recommendation: {result['recommendation']['vcpu']} vCPU(s), {result['recommendation']['ram_gb']} GB RAM")
    
    return True


def generate_comparison_table(results):
    """Generate a comparison table of all results."""
    print("\n")
    print_separator()
    print("📊 COMPARISON TABLE")
    print_separator()
    
    # Group by category
    categories = {}
    for img, res in results.items():
        if "error" not in res:
            category = res.get("category", "Other")
            if category not in categories:
                categories[category] = []
            categories[category].append((img, res))
    
    # Print each category
    for category, items in categories.items():
        print(f"\n{category}")
        print("-" * 80)
        print(f"{'Image':<25} {'CPU Peak':<12} {'RAM Peak':<15} {'Recommendation':<30}")
        print("-" * 80)
        
        for img_name, res in items:
            cpu_peak = f"{res['cpu_peak']:.2f}%"
            ram_peak = format_size(res['mem_peak_mb'])
            rec = f"{res['recommendation']['vcpu']} vCPU, {res['recommendation']['ram_gb']} GB"
            
            # Truncate long image names
            display_name = img_name if len(img_name) <= 24 else img_name[:21] + "..."
            
            print(f"{display_name:<25} {cpu_peak:<12} {ram_peak:<15} {rec:<30}")


def save_full_report(results, duration, test_time):
    """Save comprehensive report to JSON."""
    report = {
        "test_metadata": {
            "timestamp": test_time,
            "duration_per_image": duration,
            "total_images_tested": len(results),
            "successful_tests": len([r for r in results.values() if "error" not in r]),
            "failed_tests": len([r for r in results.values() if "error" in r])
        },
        "results": results
    }
    
    filename = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=4)
    
    print(f"\n📁 Full report saved to: {filename}")
    return filename


def main():
    parser = argparse.ArgumentParser(
        description="Automated test runner for Docker Resource Estimator",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--duration', '-d',
        type=int,
        default=20,
        help='Test duration per image in seconds (default: 20)'
    )
    
    parser.add_argument(
        '--quick', '-q',
        action='store_true',
        help='Run quick test with subset of images'
    )
    
    parser.add_argument(
        '--image', '-i',
        type=str,
        help='Test only a specific image (e.g., nginx:latest)'
    )
    
    args = parser.parse_args()
    
    # Select test set
    if args.image:
        # Test single image
        test_set = [img for img in TEST_IMAGES if img['name'] == args.image]
        if not test_set:
            print(f"❌ Image '{args.image}' not found in test configuration")
            print("\nAvailable images:")
            for img in TEST_IMAGES:
                print(f"  - {img['name']}")
            sys.exit(1)
    elif args.quick:
        test_set = QUICK_TEST_IMAGES
    else:
        test_set = TEST_IMAGES
    
    print("=" * 80)
    print("🐳 DOCKER RESOURCE ESTIMATOR - AUTOMATED TEST SUITE")
    print("=" * 80)
    print(f"\nTest Configuration:")
    print(f"  • Images to test: {len(test_set)}")
    print(f"  • Duration per image: {args.duration} seconds")
    print(f"  • Estimated total time: ~{len(test_set) * (args.duration + 10)} seconds")
    print()
    
    response = input("Start testing? (y/n): ").strip().lower()
    if response != 'y':
        print("Test cancelled.")
        sys.exit(0)
    
    print("\n🚀 Starting tests...\n")
    print_separator()
    
    results = {}
    test_time = datetime.now().isoformat()
    
    for idx, image_config in enumerate(test_set, 1):
        print(f"\n⏱️  [{idx}/{len(test_set)}] Starting test for {image_config['name']}...")
        
        # Add startup delay if configured
        startup_delay = image_config.get('startup_delay', 0)
        if startup_delay > 0:
            print(f"   ⏳ Allowing {startup_delay}s extra for container initialization...")
        
        start = time.time()
        result = run_estimation(
            image_config['name'],
            args.duration,
            image_config['command'],
            startup_delay
        )
        elapsed = time.time() - start
        
        # Add metadata to result
        if "error" not in result:
            result["category"] = image_config["category"]
            result["description"] = image_config["description"]
        
        results[image_config['name']] = result
        
        success = print_result(image_config, result, idx, len(test_set))
        print(f"   Time elapsed: {elapsed:.1f}s")
        
        # Small delay between tests
        if idx < len(test_set):
            time.sleep(2)
    
    # Print summary
    print("\n")
    print_separator()
    print("✅ TESTING COMPLETE")
    print_separator()
    
    successful = len([r for r in results.values() if "error" not in r])
    failed = len([r for r in results.values() if "error" in r])
    
    print(f"\nResults Summary:")
    print(f"  ✅ Successful: {successful}/{len(test_set)}")
    print(f"  ❌ Failed: {failed}/{len(test_set)}")
    
    if failed > 0:
        print(f"\nFailed images:")
        for img_name, result in results.items():
            if "error" in result:
                print(f"  • {img_name}: {result['error']}")
    
    # Generate comparison table for successful tests
    if successful > 0:
        generate_comparison_table(results)
    
    # Save full report
    report_file = save_full_report(results, args.duration, test_time)
    
    print(f"\n{'='*80}")
    print("🎉 All tests completed!")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Testing interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        sys.exit(1)
