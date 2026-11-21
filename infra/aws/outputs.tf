output "hostname" {
  description = "Public HTTPS origin of the app"
  value       = "https://${var.hostname}"
}

output "static_ip" {
  value = aws_lightsail_static_ip.app.ip_address
}

output "instance_name" {
  value = aws_lightsail_instance.app.name
}

output "region" {
  value = var.region
}

output "monthly_usd" {
  description = "Lightsail plan price, before S3 backup storage"
  value       = "7.00 (micro_3_1)"
}

output "private_key_pem" {
  description = "SSH key for the instance. Written to ~/.ssh/nirvaah-app.pem by deploy.ps1"
  value       = aws_lightsail_key_pair.app.private_key
  sensitive   = true
}
