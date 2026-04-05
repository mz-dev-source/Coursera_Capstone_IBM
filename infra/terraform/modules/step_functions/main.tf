variable "state_machine_name" { type = string }
variable "definition_file"    { type = string }
variable "environment"        { type = string }
variable "lambda_arns"        { type = list(string) }

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "sfn_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn_exec" {
  name               = "${var.state_machine_name}-exec-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume_role.json
}

data "aws_iam_policy_document" "sfn_permissions" {
  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = var.lambda_arns
  }

  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogDelivery", "logs:PutLogEvents", "logs:CreateLogGroup"]
    resources = ["*"]
  }

  statement {
    effect    = "Allow"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn_permissions" {
  name   = "${var.state_machine_name}-policy"
  role   = aws_iam_role.sfn_exec.id
  policy = data.aws_iam_policy_document.sfn_permissions.json
}

resource "aws_sfn_state_machine" "this" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.sfn_exec.arn

  definition = file(var.definition_file)

  logging_configuration {
    level                  = "ERROR"
    include_execution_data = false
  }

  tracing_configuration {
    enabled = true
  }
}

output "state_machine_arn"  { value = aws_sfn_state_machine.this.arn }
output "state_machine_name" { value = aws_sfn_state_machine.this.name }
