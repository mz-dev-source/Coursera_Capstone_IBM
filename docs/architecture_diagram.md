# Architecture Diagram — Mermaid.js

The diagram below can be rendered at [mermaid.live](https://mermaid.live),
in GitHub Markdown, or any Mermaid-compatible tool.

```mermaid
flowchart LR
    subgraph CI_CD["CI/CD Pipeline"]
        GHA["GitHub Actions"]
    end

    subgraph Security["Security Layer"]
        IAM["IAM Roles\n(Least Privilege)"]
        SM["Secrets Manager"]
    end

    subgraph API["API Layer"]
        APIGW["API Gateway\nHTTP API v2\nGET /jobs\nPOST /generate-cv\nGET /tech-trends\nGET /summary"]
    end

    subgraph Orchestration["Orchestration"]
        EB["EventBridge\nScheduler\ncron(0 7 * * ? *)"]
        SFN["Step Functions\nParallel Execution\n+ Retry + Error Handling"]
    end

    subgraph Agents["Lambda Agents"]
        JOB["Job Search\nAgent λ"]
        CV["CV Optimization\nAgent λ"]
        RADAR["Tech Radar\nAgent λ"]
        SUMMARY["Daily Summary\nAgent λ"]
    end

    subgraph AI["AI / LLM Layer"]
        BEDROCK["Amazon Bedrock\nClaude 3 Sonnet"]
    end

    subgraph Storage["Storage Layer"]
        DDB_JOBS["DynamoDB\nJobs Table"]
        DDB_CVS["DynamoDB\nCVs Table"]
        DDB_RADAR["DynamoDB\nTech Radar Table"]
        DDB_SUMMARY["DynamoDB\nSummary Table"]
        S3["S3 Bucket\nCV Storage"]
    end

    subgraph Observability["Observability"]
        CW["CloudWatch\nLogs + Dashboard\n+ X-Ray Tracing"]
    end

    subgraph Notifications["Notifications"]
        SNS["SNS Topic\nDaily Digest Email"]
    end

    GHA -->|"terraform apply"| APIGW

    APIGW -->|"GET /jobs"| JOB
    APIGW -->|"POST /generate-cv"| CV
    APIGW -->|"GET /tech-trends"| RADAR
    APIGW -->|"GET /summary"| SUMMARY

    EB -->|"daily trigger"| SFN
    SFN -->|"parallel invoke"| JOB
    SFN -->|"parallel invoke"| CV
    SFN -->|"parallel invoke"| RADAR
    SFN -->|"after parallel"| SUMMARY

    JOB -->|"InvokeModel"| BEDROCK
    CV  -->|"InvokeModel"| BEDROCK
    RADAR -->|"InvokeModel"| BEDROCK
    SUMMARY -->|"InvokeModel"| BEDROCK

    JOB --> DDB_JOBS
    CV --> DDB_CVS
    CV --> S3
    RADAR --> DDB_RADAR
    SUMMARY --> DDB_SUMMARY
    SUMMARY --> SNS

    JOB --> CW
    CV  --> CW
    RADAR --> CW
    SUMMARY --> CW

    IAM -.->|"least-privilege"| JOB
    IAM -.->|"least-privilege"| CV
    IAM -.->|"least-privilege"| RADAR
    IAM -.->|"least-privilege"| SUMMARY
    SM  -.->|"no hardcoded secrets"| BEDROCK
```

## Data Flow (End-to-End)

1. **User request** arrives at API Gateway over HTTPS.
2. API Gateway **routes** the request to the appropriate Lambda agent.
3. The Lambda agent **builds a structured prompt** from request parameters.
4. The agent calls **Amazon Bedrock** (Claude 3 Sonnet) via the shared `bedrock_client` utility.
5. Bedrock returns a **structured JSON response**.
6. The agent **persists results** to DynamoDB (and S3 for CVs).
7. The agent **returns the response** to API Gateway → client.
8. **Daily at 07:00 UTC** EventBridge triggers Step Functions.
9. Step Functions runs all agents **in parallel**, then calls the Summary agent.
10. The Summary agent **aggregates** all recent results and publishes to SNS.

## Event-Driven Triggers

| Trigger | Target | Schedule / Event |
|---------|--------|-----------------|
| EventBridge Scheduler | Step Functions | `cron(0 7 * * ? *)` — 07:00 UTC daily |
| API Gateway | Lambda (all agents) | On every HTTP request |
| Step Functions | Lambda (all agents) | On workflow execution |
