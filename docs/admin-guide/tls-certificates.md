# TLS Certificates

NetTap uses HTTPS for all dashboard and API access. By default, a self-signed certificate is generated during installation. This page covers how to configure custom certificates.

---

## Default Setup

During installation, `scripts/generate-cert.sh` creates a self-signed TLS certificate and key:

- **Certificate:** `docker/ssl/nettap.crt`
- **Private key:** `docker/ssl/nettap.key`

The nginx reverse proxy (`nettap-nginx`) uses these files for TLS termination on port 443.

!!! note "Browser warnings"
    Self-signed certificates cause browser security warnings. This is expected and safe for LAN-only access. You can add a permanent exception in your browser, or replace the certificate with one trusted by your devices.

---

## Using a Custom Certificate

### Option 1: Let's Encrypt (via DNS challenge)

If you have a domain name and can configure DNS, you can use Let's Encrypt for a free, trusted certificate. Since NetTap is typically not publicly accessible, use a DNS-01 challenge:

```bash
# Install certbot with DNS plugin (example: Cloudflare)
sudo apt install certbot python3-certbot-dns-cloudflare

# Create credentials file
cat > /etc/letsencrypt/cloudflare.ini << EOF
dns_cloudflare_api_token = your-cloudflare-api-token
EOF
chmod 600 /etc/letsencrypt/cloudflare.ini

# Request certificate
sudo certbot certonly \
  --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d nettap.yourdomain.com

# Copy to NetTap SSL directory
sudo cp /etc/letsencrypt/live/nettap.yourdomain.com/fullchain.pem /opt/nettap/docker/ssl/nettap.crt
sudo cp /etc/letsencrypt/live/nettap.yourdomain.com/privkey.pem /opt/nettap/docker/ssl/nettap.key

# Restart nginx
docker restart nettap-nginx
```

### Option 2: Private CA

If you run a private certificate authority (e.g., with `step-ca`, `mkcert`, or Active Directory Certificate Services):

```bash
# Generate a certificate signed by your CA
# ... (depends on your CA tool)

# Copy certificate and key
sudo cp your-cert.pem /opt/nettap/docker/ssl/nettap.crt
sudo cp your-key.pem /opt/nettap/docker/ssl/nettap.key

# Set permissions
sudo chmod 644 /opt/nettap/docker/ssl/nettap.crt
sudo chmod 600 /opt/nettap/docker/ssl/nettap.key

# Restart nginx
docker restart nettap-nginx
```

### Option 3: mkcert (Development/Home Use)

`mkcert` creates locally-trusted certificates. Install the root CA on your devices once, then all certificates it issues are trusted:

```bash
# Install mkcert
sudo apt install libnss3-tools
wget https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-linux-amd64
chmod +x mkcert-linux-amd64
sudo mv mkcert-linux-amd64 /usr/local/bin/mkcert

# Install the root CA (do this on the NetTap host)
mkcert -install

# Generate certificate
mkcert -cert-file /opt/nettap/docker/ssl/nettap.crt \
       -key-file /opt/nettap/docker/ssl/nettap.key \
       nettap.local 192.168.1.100 localhost

# Restart nginx
docker restart nettap-nginx
```

Then install the mkcert root CA (`~/.local/share/mkcert/rootCA.pem`) on each device that accesses the dashboard.

---

## Certificate Requirements

The certificate must:

- Be in PEM format
- Include the hostname or IP used to access the dashboard in the Subject Alternative Name (SAN)
- Have the private key unencrypted (no passphrase)

Common SANs to include:

- `nettap.local` (mDNS hostname)
- The management IP address (e.g., `192.168.1.100`)
- `localhost` (for local access)

---

## Regenerating the Self-Signed Certificate

To regenerate the default self-signed certificate:

```bash
sudo scripts/generate-cert.sh
docker restart nettap-nginx
```

---

## Malcolm TLS

The Malcolm stack (accessible on port 9443) uses its own TLS certificates generated during Malcolm deployment. These are stored in the `MALCOLM_CERTS_DIR` (default: `docker/certs/`) and are separate from the NetTap dashboard certificate.

To access Malcolm dashboards without certificate warnings, you would need to replace the Malcolm certificates as well. Refer to the [Malcolm documentation](https://malcolm.fyi/) for details.

---

## Verifying Certificates

```bash
# Check the current certificate
openssl x509 -in /opt/nettap/docker/ssl/nettap.crt -text -noout

# Test the HTTPS connection
curl -vk https://localhost:443 2>&1 | grep -E "subject|issuer|expire"

# Check certificate expiry
openssl x509 -in /opt/nettap/docker/ssl/nettap.crt -enddate -noout
```
