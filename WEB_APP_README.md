# Docker Resource Estimator - Web Application

A beautiful Flask web application for profiling Docker containers and getting cloud instance recommendations.

## Features

### 🎨 Beautiful Modern UI
- Responsive gradient design
- Real-time progress tracking
- Interactive cards and animations
- Mobile-friendly interface

### 📊 Bulk Testing
- Test all 10 default Docker images:
  - Web Servers: Nginx, Apache
  - Databases: Redis, PostgreSQL, MySQL
  - Languages: Python 3.11, Node.js 18, OpenJDK 17
  - Base Images: Alpine Linux, Ubuntu
- Live progress updates
- Grouped results by category
- Comparison tables

### 🎯 Single Image Testing
- Test any Docker image from Docker Hub
- Custom command support
- Configurable test duration
- Detailed resource metrics

### ☁️ Cloud Recommendations
- Instance recommendations for:
  - **AWS**: t3 family instances
  - **Google Cloud**: e2 family instances
  - **Azure**: B family instances
- Based on actual resource usage
- vCPU and RAM estimates

## Installation

### Prerequisites
- Python 3.7+
- Docker Desktop (running)

### Setup

1. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```

2. **Ensure Docker is running:**
   ```powershell
   docker ps
   ```

3. **Run the Flask app:**
   ```powershell
   python app.py
   ```

4. **Open your browser:**
   ```
   http://localhost:5000
   ```

## Usage

### Home Page
- Choose between Bulk Test or Single Image Test
- View feature list

### Bulk Test
1. Click "Run All Tests"
2. Configure test duration (default: 20 seconds per image)
3. Click "Start Bulk Test"
4. Watch real-time progress
5. View comprehensive results with cloud recommendations

### Single Image Test
1. Click "Test Custom Image"
2. Enter Docker image name (e.g., `nginx:latest`)
3. Set test duration (default: 30 seconds)
4. Optionally add custom command
5. Click "Start Test"
6. View detailed results

## Screenshots

### Home Page
- Modern gradient design with two main options
- Feature list at the bottom

### Bulk Test Progress
- Real-time progress bar
- Current image being tested
- Number of completed tests

### Results Page
- Categorized results (Web Servers, Databases, Languages, Base Images)
- CPU and Memory metrics (Average and Peak)
- Cloud instance recommendations for AWS, GCP, Azure
- Success/failure badges

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Home page |
| `/bulk-test` | GET | Bulk test configuration page |
| `/single-test` | GET | Single image test form |
| `/results?type=bulk` | GET | Bulk test results |
| `/results?type=single` | GET | Single test results |
| `/api/start-bulk-test` | POST | Start bulk testing |
| `/api/bulk-test-progress` | GET | Get bulk test progress (JSON) |
| `/api/start-single-test` | POST | Start single image test |

## Architecture

### Backend
- **Flask** web framework
- **Docker Python SDK** for container management
- **Threading** for background test execution
- **Sessions** for storing single test results

### Frontend
- **Embedded HTML/CSS** in Python file (no separate template files)
- **Vanilla JavaScript** for AJAX requests
- **Responsive CSS Grid** layout
- **Real-time progress polling**

### Resource Estimation Algorithm
1. Pull/check Docker image
2. Start container with keep-alive command
3. Collect CPU and memory stats every second
4. Calculate delta-based CPU usage (accurate)
5. Track peak and average values
6. Stop and remove container
7. Generate recommendations based on peaks

## Configuration

### Default Images
Edit `DEFAULT_TEST_IMAGES` in `app.py` to customize the bulk test images.

### Test Duration
- Bulk Test: Configurable per run (default: 20 seconds per image)
- Single Test: Configurable per test (default: 30 seconds)

### Port
Change the port in the last line of `app.py`:
```python
app.run(debug=True, host='0.0.0.0', port=5000)  # Change 5000 to your port
```

## Troubleshooting

### Docker Not Running
**Error:** `Error while fetching server API version`

**Solution:**
```powershell
# Start Docker Desktop and wait for it to fully initialize
docker ps
```

### Port Already in Use
**Error:** `Address already in use`

**Solution:**
```powershell
# Change the port in app.py or kill the process using port 5000
netstat -ano | findstr :5000
taskkill /PID <PID> /F
```

### Import Error for Flask
**Error:** `ModuleNotFoundError: No module named 'flask'`

**Solution:**
```powershell
pip install flask
```

### Test Timeouts
- Some images may take longer to start
- Increase test duration for database images
- Ensure images have proper keep-alive commands

## Performance

- **Bulk Test (10 images)**: ~3-5 minutes
- **Single Test**: ~30-60 seconds
- **Memory Usage**: ~50-100 MB for Flask app
- **CPU Usage**: Minimal when idle, moderate during testing

## Security Notes

- This is a development server (Flask debug mode)
- For production, use a proper WSGI server (Gunicorn, uWSGI)
- Docker socket access required (run as admin on Windows)
- No authentication implemented (add if exposing publicly)

## Future Enhancements

- [ ] Export results to PDF/CSV
- [ ] Historical test tracking
- [ ] Cost estimation per cloud provider
- [ ] Docker Compose support
- [ ] Kubernetes resource recommendations
- [ ] User authentication
- [ ] Database for test history
- [ ] Comparison between multiple tests
- [ ] Email notifications on test completion

## License

MIT License

## Author

Built for cloud infrastructure planning and Docker container optimization.

---

**Made with ❤️ using Flask and Docker**
