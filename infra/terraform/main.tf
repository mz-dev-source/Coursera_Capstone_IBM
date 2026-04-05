terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    # Override these values per environment using -backend-config flags or a
    # backend.hcl file.  Do NOT hard-code bucket names or region here.
    # Example:
    #   terraform init -backend-config=env/prod/backend.hcl
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ai-agent-platform"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# ── Variables ────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev / staging / prod)"
  type        = string
  default     = "dev"
}

variable "lambda_runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.12"
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 512
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock model identifier"
  type        = string
  default     = "anthropic.claude-3-sonnet-20240229-v1:0"
}

variable "sns_email" {
  description = "E-mail address for daily summary notifications (optional)"
  type        = string
  default     = ""
}

# ── Data sources ─────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ── S3 — CV Storage ──────────────────────────────────────────────────────────

resource "aws_s3_bucket" "cv_storage" {
  bucket = "ai-platform-cv-storage-${data.aws_caller_identity.current.account_id}-${var.environment}"
}

resource "aws_s3_bucket_versioning" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cv_storage" {
  bucket = aws_s3_bucket.cv_storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cv_storage" {
  bucket                  = aws_s3_bucket.cv_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── DynamoDB Tables ───────────────────────────────────────────────────────────

module "jobs_table" {
  source      = "./modules/dynamodb"
  table_name  = "ai-platform-jobs-${var.environment}"
  environment = var.environment
}

module "cv_table" {
  source      = "./modules/dynamodb"
  table_name  = "ai-platform-cvs-${var.environment}"
  environment = var.environment
}

module "tech_radar_table" {
  source      = "./modules/dynamodb"
  table_name  = "ai-platform-tech-radar-${var.environment}"
  environment = var.environment
}

module "summary_table" {
  source      = "./modules/dynamodb"
  table_name  = "ai-platform-summaries-${var.environment}"
  environment = var.environment
}

# ── IAM — Lambda Execution Role ───────────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "ai-platform-lambda-exec-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_permissions" {
  # CloudWatch Logs
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
  }

  # X-Ray tracing
  statement {
    effect    = "Allow"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }

  # Amazon Bedrock — restricted to specific model
  statement {
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"]
  }

  # DynamoDB — scoped to platform tables only
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem",
    ]
    resources = [
      module.jobs_table.table_arn,
      module.cv_table.table_arn,
      module.tech_radar_table.table_arn,
      module.summary_table.table_arn,
    ]
  }

  # S3 — CV bucket only, no public listing
  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.cv_storage.arn}/cvs/*"]
  }

  # SNS — publish to summary topic only
  dynamic "statement" {
    for_each = var.sns_email != "" ? [1] : []
    content {
      effect    = "Allow"
      actions   = ["sns:Publish"]
      resources = [aws_sns_topic.daily_summary[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "lambda_permissions" {
  name   = "ai-platform-lambda-policy-${var.environment}"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# Attach basic Lambda execution policy (VPC access, ENI creation, etc.)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ── Lambda Functions ──────────────────────────────────────────────────────────

locals {
  common_env_vars = {
    JOBS_TABLE         = module.jobs_table.table_name
    CV_TABLE           = module.cv_table.table_name
    TECH_RADAR_TABLE   = module.tech_radar_table.table_name
    SUMMARY_TABLE      = module.summary_table.table_name
    CV_BUCKET          = aws_s3_bucket.cv_storage.bucket
    BEDROCK_MODEL_ID   = var.bedrock_model_id
    AWS_REGION         = var.aws_region
    POWERTOOLS_SERVICE = "ai-agent-platform"
    LOG_LEVEL          = "INFO"
  }
}

module "job_agent_lambda" {
  source        = "./modules/lambda"
  function_name = "ai-platform-job-agent-${var.environment}"
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory
  source_dir    = "${path.root}/../../services/job_agent"
  role_arn      = aws_iam_role.lambda_exec.arn
  environment   = merge(local.common_env_vars, {})
  layers        = []
}

module "cv_agent_lambda" {
  source        = "./modules/lambda"
  function_name = "ai-platform-cv-agent-${var.environment}"
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 120
  memory_size   = var.lambda_memory
  source_dir    = "${path.root}/../../services/cv_agent"
  role_arn      = aws_iam_role.lambda_exec.arn
  environment   = merge(local.common_env_vars, {})
  layers        = []
}

module "tech_radar_agent_lambda" {
  source        = "./modules/lambda"
  function_name = "ai-platform-tech-radar-agent-${var.environment}"
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory
  source_dir    = "${path.root}/../../services/tech_radar_agent"
  role_arn      = aws_iam_role.lambda_exec.arn
  environment   = merge(local.common_env_vars, {})
  layers        = []
}

module "summary_agent_lambda" {
  source        = "./modules/lambda"
  function_name = "ai-platform-summary-agent-${var.environment}"
  handler       = "handler.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 120
  memory_size   = var.lambda_memory
  source_dir    = "${path.root}/../../services/summary_agent"
  role_arn      = aws_iam_role.lambda_exec.arn
  environment   = merge(local.common_env_vars, {
    SNS_TOPIC_ARN = var.sns_email != "" ? aws_sns_topic.daily_summary[0].arn : ""
  })
  layers = []
}

# ── API Gateway ───────────────────────────────────────────────────────────────

module "api_gateway" {
  source      = "./modules/api_gateway"
  api_name    = "ai-agent-platform-${var.environment}"
  environment = var.environment

  lambda_integrations = {
    "GET /jobs"         = module.job_agent_lambda.function_invoke_arn
    "POST /generate-cv" = module.cv_agent_lambda.function_invoke_arn
    "GET /tech-trends"  = module.tech_radar_agent_lambda.function_invoke_arn
    "GET /summary"      = module.summary_agent_lambda.function_invoke_arn
  }

  lambda_function_names = {
    "GET /jobs"         = module.job_agent_lambda.function_name
    "POST /generate-cv" = module.cv_agent_lambda.function_name
    "GET /tech-trends"  = module.tech_radar_agent_lambda.function_name
    "GET /summary"      = module.summary_agent_lambda.function_name
  }
}

# ── Step Functions ────────────────────────────────────────────────────────────

module "step_functions" {
  source              = "./modules/step_functions"
  state_machine_name  = "ai-agent-orchestrator-${var.environment}"
  definition_file     = "${path.root}/../step_functions_definition.json"
  environment         = var.environment
  lambda_arns = [
    module.job_agent_lambda.function_arn,
    module.cv_agent_lambda.function_arn,
    module.tech_radar_agent_lambda.function_arn,
    module.summary_agent_lambda.function_arn,
  ]
}

# ── EventBridge Scheduler — Daily Summary ─────────────────────────────────────

module "eventbridge" {
  source             = "./modules/eventbridge"
  rule_name          = "daily-summary-trigger-${var.environment}"
  schedule_expression = "cron(0 7 * * ? *)"
  target_arn         = module.summary_agent_lambda.function_arn
  target_name        = module.summary_agent_lambda.function_name
  environment        = var.environment
}

# ── SNS — Daily Summary Notifications (optional) ─────────────────────────────

resource "aws_sns_topic" "daily_summary" {
  count             = var.sns_email != "" ? 1 : 0
  name              = "ai-platform-daily-summary-${var.environment}"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "daily_summary_email" {
  count     = var.sns_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.daily_summary[0].arn
  protocol  = "email"
  endpoint  = var.sns_email
}

# ── CloudWatch Dashboard ──────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "platform" {
  dashboard_name = "ai-agent-platform-${var.environment}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Invocations"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", module.job_agent_lambda.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", module.cv_agent_lambda.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", module.tech_radar_agent_lambda.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", module.summary_agent_lambda.function_name],
          ]
          period = 300
          stat   = "Sum"
          region = var.aws_region
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Errors"
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", module.job_agent_lambda.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", module.cv_agent_lambda.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", module.tech_radar_agent_lambda.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", module.summary_agent_lambda.function_name],
          ]
          period = 300
          stat   = "Sum"
          region = var.aws_region
        }
      }
    ]
  })
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "api_endpoint" {
  description = "API Gateway invoke URL"
  value       = module.api_gateway.api_endpoint
}

output "job_agent_function_name" {
  description = "Job Agent Lambda function name"
  value       = module.job_agent_lambda.function_name
}

output "cv_agent_function_name" {
  description = "CV Agent Lambda function name"
  value       = module.cv_agent_lambda.function_name
}

output "tech_radar_agent_function_name" {
  description = "Tech Radar Agent Lambda function name"
  value       = module.tech_radar_agent_lambda.function_name
}

output "summary_agent_function_name" {
  description = "Summary Agent Lambda function name"
  value       = module.summary_agent_lambda.function_name
}

output "state_machine_arn" {
  description = "Step Functions state machine ARN"
  value       = module.step_functions.state_machine_arn
}
