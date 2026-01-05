
# Workflow

```
flowchart TD
    START([Start])

    INPUT[User provides image name\n test duration\n execution mode]
    CHECK[Check Docker image availability]
    EXISTS{Image available}

    PULL[Pull image from registry]
    RUN[Start container with keep alive command]
    WAIT[Wait for container startup]

    COLLECT[Collect CPU and memory statistics]
    CPU[Calculate CPU usage using delta method]
    MEM[Measure memory usage]

    ANALYZE[Analyze average and peak usage]
    RECOMMEND[Generate resource recommendation]

    MAP[Map resources to cloud instances]
    SAVE[Save results as JSON file]

    CLEANUP[Stop and remove container]
    OUTPUT[Display results to user]

    END([End])

    START --> INPUT
    INPUT --> CHECK
    CHECK --> EXISTS

    EXISTS -- No --> PULL
    EXISTS -- Yes --> RUN
    PULL --> RUN

    RUN --> WAIT
    WAIT --> COLLECT

    COLLECT --> CPU
    COLLECT --> MEM

    CPU --> ANALYZE
    MEM --> ANALYZE

    ANALYZE --> RECOMMEND
    RECOMMEND --> MAP
    MAP --> SAVE

    SAVE --> CLEANUP
    CLEANUP --> OUTPUT
    OUTPUT --> END
```

---

# Architecture

```
graph TD
    %% User Layer
    U[User or DevOps Engineer]

    %% Interfaces
    CLI[CLI Tool\n docker_resource_estimator.py]
    TR[Test Runner\n test_runner.py]
    WEB[Flask Web Application\n app.py]

    %% Core Processing
    PROFILER[Resource Estimation Engine]
    ANALYZER[CPU and Memory Analyzer\n Delta based calculation]
    RECOMMENDER[Cloud Recommendation Engine]

    %% Docker Layer
    DOCKER_API[Docker Engine API]
    CONTAINER[Running Docker Containers]
    STATS[Docker Statistics API]

    %% Output Layer
    JSON[JSON Result Files]
    CLOUD[Cloud Providers\n AWS GCP Azure]

    %% Connections
    U --> CLI
    U --> TR
    U --> WEB

    CLI --> PROFILER
    TR --> PROFILER
    WEB --> PROFILER

    PROFILER --> DOCKER_API
    DOCKER_API --> CONTAINER
    CONTAINER --> STATS
    STATS --> ANALYZER

    ANALYZER --> RECOMMENDER
    RECOMMENDER --> CLOUD
    RECOMMENDER --> JSON

    JSON --> CLI
    JSON --> TR
    JSON --> WEB
```

# Web Architecture

```
sequenceDiagram
    participant User
    participant Browser
    participant FlaskApp
    participant BackgroundThread
    participant Docker
    participant Container

    User->>Browser: Open Web UI
    Browser->>FlaskApp: Start bulk/single test (POST)
    FlaskApp->>BackgroundThread: Spawn background task
    FlaskApp-->>Browser: Test started

    loop Every 1 second
        Browser->>FlaskApp: Poll progress API
        FlaskApp-->>Browser: Progress JSON
    end

    BackgroundThread->>Docker: Start container
    Docker->>Container: Run image
    Container-->>Docker: Resource stats
    Docker-->>BackgroundThread: CPU & memory data

    BackgroundThread->>FlaskApp: Save results
    FlaskApp-->>Browser: Test complete
    Browser->>User: Display results & cloud recommendations

```
---

# Block Diagram Architecture

```
flowchart LR
    %% User Block
    USER[User]

    %% Interface Layer
    CLI[CLI Interface]
    TEST[Test Runner]
    WEB[Web Interface]

    %% Core Processing
    ENGINE[Resource Estimation Engine]
    ANALYSIS[CPU and Memory Analysis]
    RECOMMEND[Recommendation Engine]

    %% Docker Layer
    DOCKER[Docker Engine API]
    CONTAINER[Docker Containers]
    STATS[Resource Statistics]

    %% Output Layer
    OUTPUT[JSON Reports]
    CLOUD[Cloud Instance Mapping]

    %% Connections
    USER --> CLI
    USER --> TEST
    USER --> WEB

    CLI --> ENGINE
    TEST --> ENGINE
    WEB --> ENGINE

    ENGINE --> DOCKER
    DOCKER --> CONTAINER
    CONTAINER --> STATS

    STATS --> ANALYSIS
    ANALYSIS --> RECOMMEND

    RECOMMEND --> CLOUD
    RECOMMEND --> OUTPUT

    OUTPUT --> USER

```