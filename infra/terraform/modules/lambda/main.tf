variable "function_name" { type = string }
variable "handler"       { type = string }
variable "runtime"       { type = string }
variable "timeout"       { type = number }
variable "memory_size"   { type = number }
variable "source_dir"    { type = string }
variable "role_arn"      { type = string }
variable "environment"   { type = map(string) }
variable "layers"        { type = list(string) }

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "/tmp/${var.function_name}.zip"
}

resource "aws_lambda_function" "this" {
  function_name    = var.function_name
  handler          = var.handler
  runtime          = var.runtime
  timeout          = var.timeout
  memory_size      = var.memory_size
  role             = var.role_arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  layers           = var.layers

  environment {
    variables = var.environment
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Function = var.function_name
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = 14
}

output "function_arn"        { value = aws_lambda_function.this.arn }
output "function_name"       { value = aws_lambda_function.this.function_name }
output "function_invoke_arn" { value = aws_lambda_function.this.invoke_arn }
