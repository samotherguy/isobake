# webhook

On first boot, POSTs a JSON record (hostname, machine-id, MAC, IP, SSH host
public key) to `vars.webhook_url`. Point it at anything that accepts JSON: a
Google Form bridge, n8n, a Slack webhook relay, your own inventory API.
