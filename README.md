# Everpure ZTP File Server

A web-based file server built with Flask to support **Zero Touch Provisioning (ZTP)** of Pure Storage FlashArray appliances. It hosts Purity software packages and provides browser-based tools to trigger ZTP operations directly against FlashArray controllers via the REST API.

## Features

- **File Management** — Upload, download, delete, and move files through a browser UI. Fetch files directly from remote URLs.
- **ZTP PureSoftwareInstall** — Initiates a Purity software installation on a FlashArray by sending a PATCH request to the array's ZTP endpoint.
- **ZTP PureInitialize** — Sends the full initial configuration (networking, DNS, NTP, SMTP, EULA) to an uninitialized FlashArray via the REST API.

## Requirements

- Python 3
- Flask (`python3-flask`)
- RHEL / CentOS / Fedora / Ubuntu (setup script supports all)

## Running with Docker (Recommended)

```bash
git clone git@github.com:wwt/Everpure-ZTP.git
cd Everpure-ZTP
docker compose build --no-cache && docker compose up -d
```

The server will be available at `http://<host-ip>:8080`.

Uploaded files are persisted in `./files/` on the host via a volume mount and survive container restarts.

To stop:

```bash
docker compose down
```

> **Note:** The DHCP Server feature does not work when running in a Docker container on macOS or Windows. Docker Desktop does not support true host networking on those platforms, which is required for the DHCP server to bind to a physical interface. See [DHCP Server](#dhcp-server) below for details.

## Installation (Bare Metal / VM)

```bash
sudo bash /home/atcadmin/fileserver/setup.sh
```

This installs Flask, creates the file storage directory, registers/starts the `fileserver` systemd service on port 8080, and opens port 8080 in the firewall (via `firewall-cmd` on RHEL/CentOS/Fedora).

If your distro uses `ufw` instead, open the port manually:

```bash
sudo ufw allow 8080/tcp
```

## Configuration

| Setting | Default | Description |
|---|---|---|
| `FILE_SERVER_ROOT` | `/home/atcadmin/fileserver/files` | Root directory for uploaded files |
| Port | `8080` | Set in `app.py` and `docker-compose.yml` |
| Logo assets | `assets/` | Served at `/logos/` |

To change the file storage root, edit `fileserver.service`:

```ini
Environment=FILE_SERVER_ROOT=/your/path/here
```

Then reload:

```bash
sudo systemctl daemon-reload && sudo systemctl restart fileserver
```

## ZTP PureSoftwareInstall

Triggers a Purity package installation on a FlashArray over ZTP.

- **Endpoint used:** `PATCH http://<ct1.eth0 IP>:8081/array-purity-installations`
- **Required inputs:**
  - `ct1.eth0 ZTP IP` — The DHCP-assigned IP address of ct1.eth0 on the array
  - `.ppkg URL` — Full URL to the Purity package file (use **Copy Link** on a file in the UI)
  - `.ppkg.sig URL` — Full URL to the matching signature file
- **Optional:** DNS nameservers, search domain, and domain can be configured if package URLs use hostnames

The status panel shows live install progress through these phases:

`Not Started` → `Install In Progress` → `Downloading` → `CT0 Installing` → `CT1 Installing` → `Complete`

## ZTP PureInitialize

Sends the initial configuration to a factory-fresh FlashArray.

- **Endpoint used:** `PATCH http://<ct1.eth0 IP>:8081/array-initial-config`
- **Required inputs:**
  - `ct1.eth0 ZTP IP`
  - FlashArray name
  - IP / Netmask / Gateway for `ct0.eth0`, `ct1.eth0`, and `vir0`
  - NTP servers and timezone
  - EULA acceptance (full name, job title, organization)
- **Optional:** DNS (domain + nameservers), SMTP relay, alert email addresses

> **RC4 arrays** (using ETH4/5 as management ports): toggle **ETH4 / VIR4** in the Interface Mode selector. This switches the payload keys to `ct0.eth4`, `ct1.eth4`, and `vir4` as required.

Once initialized, use the static IPs assigned during initialization to communicate with the array. The ZTP DHCP address and the `array-initial-config` endpoint are no longer valid after initialization completes.

## DHCP Server

The built-in DHCP server lets you assign IP addresses to FlashArray controllers over a private network without needing a separate DHCP service. It is intended for use during ZTP when no other DHCP server is available on the network.

**How it works:**

1. Select the network interface connected to the FlashArray management network.
2. Set the subnet, DHCP range, and the static IP address the server itself should use on that interface.
3. Click **Enable DHCP Server**. The application assigns the configured static IP to the selected interface and starts a `dnsmasq` DHCP process.
4. When stopped, the static IP is removed from the interface and `dnsmasq` is shut down.

Active leases and dnsmasq logs are viewable from the UI without leaving the page.

> **Linux VM / bare-metal only.** The DHCP server requires direct access to the host network interface. It will not function when running inside a Docker container on macOS or Windows because Docker Desktop does not support host networking on those platforms. Use this feature only when the application is installed directly on a Linux VM or bare-metal server (via `setup.sh`).

## FlashArray ZTP Simulator

A lightweight mock container is included for testing the ZTP workflows without access to a physical FlashArray. It listens on port 8081 and simulates both ZTP API endpoints.

```bash
docker compose -f docker-compose.simulator.yml up -d
```

Once running, enter the host machine's IP address as the **Controller 1 ZTP IP** in the ZTP tool UI (e.g. `192.168.1.100`). The simulator will be reachable on port 8081.

**What it simulates:**

- **Check Status** — Returns `install-not-started` initially, then advances through all install phases automatically after a PATCH install is received
- **ZTP FlashArray Install** — Accepts the PATCH request and begins phase progression: `Not Started` → `Install In Progress` → `Downloading` → `CT0 Installing` → `CT1 Installing` → `Complete`
- **ZTP FlashArray Initialize** — Accepts the initialize PATCH payload and returns success immediately

Each phase advances every 5 seconds by default. To change the speed, edit `PHASE_DELAY` in `docker-compose.simulator.yml`.

To reset the simulator between test runs:

```bash
curl -X POST http://<host-ip>:8081/reset
```

To stop the simulator:

```bash
docker compose -f docker-compose.simulator.yml down
```

## File Storage

Uploaded files are stored under `FILE_SERVER_ROOT` and can be organized into folders. Files are served at:

```
http://<server-ip>:8080/download/<path/to/file>
```

The **Copy Link** button in the UI copies this URL to the clipboard, ready to paste into the ZTP PureSoftwareInstall package path fields.

> **Note:** The `files/` directory is excluded from this repository (`.gitignore`) due to the large size of Purity `.ppkg` firmware bundles (~5–6 GB each).

## Service Management

```bash
sudo systemctl status fileserver
sudo systemctl restart fileserver
sudo systemctl stop fileserver
```

Logs:

```bash
sudo journalctl -u fileserver -f
```
