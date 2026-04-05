variable "rule_name"            { type = string }
variable "schedule_expression"   { type = string }
variable "target_arn"            { type = string }
variable "target_name"           { type = string }
variable "environment"           { type = string }

resource "aws_cloudwatch_event_rule" "this" {
  name                = var.rule_name
  description         = "Trigger ${var.target_name} on schedule"
  schedule_expression = var.schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "this" {
  rule      = aws_cloudwatch_event_rule.this.name
  target_id = var.target_name
  arn       = var.target_arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke-${var.rule_name}"
  action        = "lambda:InvokeFunction"
  function_name = var.target_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.this.arn
}

output "rule_arn" { value = aws_cloudwatch_event_rule.this.arn }
