#!/usr/bin/env python3
"""
Architecture diagram for the AWS AI Agent Platform.

Uses the 'diagrams' library (https://diagrams.mingrammer.com/) to generate a
production-quality PNG architecture diagram.

Install dependencies:
    pip install diagrams

Run:
    python docs/architecture_diagram.py
    # → outputs docs/aws_ai_agent_platform.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.engagement import SNS
from diagrams.aws.integration import Eventbridge, StepFunctions
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Sagemaker as BedrockIcon
from diagrams.aws.network import APIGateway
from diagrams.aws.security import IAM, SecretsManager
from diagrams.aws.storage import S3
from diagrams.onprem.ci import GithubActions

graph_attr = {
    "fontsize": "14",
    "bgcolor": "#f8f9fa",
    "pad": "0.75",
    "splines": "ortho",
}

with Diagram(
    "AWS AI Agent Platform — Architecture",
    filename="docs/aws_ai_agent_platform",
    outformat="png",
    show=False,
    graph_attr=graph_attr,
    direction="LR",
):
    # ── CI/CD ──────────────────────────────────────────────────────────────
    cicd = GithubActions("GitHub Actions\nCI/CD")

    # ── Security ───────────────────────────────────────────────────────────
    with Cluster("Security"):
        iam = IAM("IAM Roles\n(Least Privilege)")
        secrets = SecretsManager("Secrets Manager")

    # ── API Layer ─────────────────────────────────────────────────────────
    with Cluster("API Layer"):
        api_gw = APIGateway("API Gateway\nHTTP API v2")

    # ── Compute — Lambda Agents ────────────────────────────────────────────
    with Cluster("Lambda Agents"):
        job_lambda = Lambda("Job Search\nAgent")
        cv_lambda = Lambda("CV Optimization\nAgent")
        radar_lambda = Lambda("Tech Radar\nAgent")
        summary_lambda = Lambda("Daily Summary\nAgent")

    # ── Orchestration ──────────────────────────────────────────────────────
    with Cluster("Orchestration"):
        sfn = StepFunctions("Step Functions\nOrchestrator")
        eb = Eventbridge("EventBridge\nScheduler")

    # ── AI Layer ──────────────────────────────────────────────────────────
    with Cluster("AI / LLM"):
        bedrock = BedrockIcon("Amazon Bedrock\nClaude 3 Sonnet")

    # ── Storage ───────────────────────────────────────────────────────────
    with Cluster("Storage"):
        ddb_jobs = Dynamodb("DynamoDB\nJobs Table")
        ddb_cvs = Dynamodb("DynamoDB\nCVs Table")
        ddb_radar = Dynamodb("DynamoDB\nTech Radar Table")
        ddb_summary = Dynamodb("DynamoDB\nSummary Table")
        s3 = S3("S3 Bucket\nCV Storage")

    # ── Observability ─────────────────────────────────────────────────────
    with Cluster("Observability"):
        cw = Cloudwatch("CloudWatch\nLogs + Dashboard")

    # ── Notifications ─────────────────────────────────────────────────────
    sns = SNS("SNS\nDaily Digest")

    # ── Edges ─────────────────────────────────────────────────────────────
    cicd >> Edge(label="deploy") >> api_gw

    api_gw >> Edge(label="GET /jobs") >> job_lambda
    api_gw >> Edge(label="POST /generate-cv") >> cv_lambda
    api_gw >> Edge(label="GET /tech-trends") >> radar_lambda
    api_gw >> Edge(label="GET /summary") >> summary_lambda

    sfn >> Edge(label="invoke") >> [job_lambda, cv_lambda, radar_lambda]
    sfn >> Edge(label="invoke") >> summary_lambda

    eb >> Edge(label="0 7 * * ?") >> sfn

    job_lambda >> Edge(label="InvokeModel") >> bedrock
    cv_lambda >> Edge(label="InvokeModel") >> bedrock
    radar_lambda >> Edge(label="InvokeModel") >> bedrock
    summary_lambda >> Edge(label="InvokeModel") >> bedrock

    job_lambda >> ddb_jobs
    cv_lambda >> ddb_cvs
    cv_lambda >> s3
    radar_lambda >> ddb_radar
    summary_lambda >> ddb_summary

    summary_lambda >> sns

    [job_lambda, cv_lambda, radar_lambda, summary_lambda] >> cw

    iam >> Edge(style="dashed") >> [job_lambda, cv_lambda, radar_lambda, summary_lambda]
    secrets >> Edge(style="dashed") >> bedrock
