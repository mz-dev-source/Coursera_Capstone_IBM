variable "table_name" {
  description = "DynamoDB table name"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

resource "aws_dynamodb_table" "this" {
  name           = var.table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "pk"
  range_key      = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Environment = var.environment
  }
}

output "table_arn"  { value = aws_dynamodb_table.this.arn }
output "table_name" { value = aws_dynamodb_table.this.name }
