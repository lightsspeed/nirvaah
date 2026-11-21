locals {
  tags = {
    Project   = "nirvaah"
    Component = "app-host"
    ManagedBy = "terraform"
  }
}

data "aws_route53_zone" "main" {
  zone_id = var.zone_id
}

# Lightsail key pairs are per region and independent of EC2 key pairs. Terraform
# generates the key material and keeps it in state; deploy.ps1 writes it to
# ~/.ssh/nirvaah-app.pem on first run.
resource "aws_lightsail_key_pair" "app" {
  name = "${var.instance_name}-key"
}

resource "aws_lightsail_instance" "app" {
  name              = var.instance_name
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.app.name

  user_data = templatefile("${path.module}/startup.sh.tftpl", {
    swap_mb = var.swap_size_mb
  })

  tags = local.tags

  # user_data is a creation-time property on Lightsail. Without this, editing
  # the startup script would destroy the instance — and the Postgres volume
  # that holds the only copy of the data on this host.
  lifecycle {
    ignore_changes = [user_data]
  }
}

# A static IP survives stop/start; the instance's own public IP does not.
resource "aws_lightsail_static_ip" "app" {
  name = "${var.instance_name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

# Lightsail's firewall is the internet edge; the OS has no ufw, so these three
# rules are the whole exposure.
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = [var.ssh_cidr]
  }

  # ACME HTTP-01 challenge and the HTTP -> HTTPS redirect.
  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}

resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.hostname
  type    = "A"
  ttl     = 60
  records = [aws_lightsail_static_ip.app.ip_address]
}
