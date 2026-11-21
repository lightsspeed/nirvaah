variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) is the cheapest India-adjacent Lightsail region."
  type        = string
  default     = "ap-south-1"
}

variable "availability_zone" {
  description = "AZ inside the region. Lightsail names are region-suffixed, e.g. ap-south-1a."
  type        = string
  default     = "ap-south-1a"
}

variable "instance_name" {
  description = "Lightsail instance name (must be unique in the account/region)."
  type        = string
  default     = "nirvaah-app"
}

variable "bundle_id" {
  description = <<-EOT
    Lightsail plan. micro_3_1 = $7/mo, 1 GB RAM, 2 vCPU, 40 GB SSD, 1 TB
    transfer — the cheapest plan the compose stack (Postgres + FastAPI +
    nginx + backup agent + Caddy) fits on with swap. small_3_1 = $12/mo, 2 GB,
    more headroom with no swap tuning needed.
  EOT
  type        = string
  default     = "micro_3_1"
}

variable "blueprint_id" {
  description = "OS image blueprint."
  type        = string
  default     = "ubuntu_24_04"
}

variable "hostname" {
  description = "Fully qualified hostname the app is served on. Must sit inside the Route 53 zone below."
  type        = string
  default     = "nirvaah.deployone.cloud"
}

variable "zone_name" {
  description = "Route 53 public hosted zone that contains hostname."
  type        = string
  default     = "deployone.cloud"
}

variable "zone_id" {
  description = "Hosted zone id (avoids an account-wide zone lookup). Empty means look it up by zone_name."
  type        = string
  default     = "Z0367959U5B4EEUTYZG0"
}

variable "ssh_cidr" {
  description = "CIDR allowed to reach SSH (22). Never 0.0.0.0/0 for an internet-facing box. Re-run with -var when your ISP rotates your address, or use deploy/allow-ip.ps1."
  type        = string
  default     = "49.36.105.212/32"
}

variable "swap_size_mb" {
  description = "Swap file size on the instance. Carries the stack through a build spike on 1 GB RAM."
  type        = number
  default     = 2048
}
