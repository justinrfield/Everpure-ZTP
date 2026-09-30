# Everpure ZTP File Server

A web-based file server built with Flask to support **Zero Touch Provisioning (ZTP)** of Pure Storage FlashArray appliances. It hosts Purity software packages and provides browser-based tools to trigger ZTP operations directly against FlashArray controllers via the REST API.

## Features

- **File Management** — Upload, download, delete, and move files through a browser UI. Fetch files directly from remote URLs.
- **ZTP PureSoftwareInstall** — Initiates a Purity software installation on a FlashArray by sending a PATCH request to the array's ZTP endpoint. Check Status auto-refreshes every 15 seconds until complete.
- **ZTP PureInitialize** — Sends the full initial configuration (networking, DNS, NTP, SMTP, EULA) to an uninitialized FlashArray via the REST API.
- **ZTE FlashArray Erasure** — Drives the full Zero Touch Erasure workflow: authenticate, start the secure wipe, monitor status, download the sanitization certificate, and finalize with image reinstallation.
- **DHCP Server** — Assigns IP addresses to FlashArray controllers over a private network (Linux VM / bare-metal only).
- **FlashArray ZTP Simulator** — Lightweight mock container for testing ZTP workflows without physical hardware.

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

## Running on Windows Server (Native Python)

No Docker required. The ZTP FlashArray Install and Initialize features run natively on
Windows with Python 3 and Flask. The DHCP Server is Linux-only and will not be available.

### Prerequisites

- **Python 3.x** — download from [python.org](https://www.python.org/downloads/)
  - During installation, check **"Add Python to PATH"**
  - After install, Python is typically invoked as `py` on Windows (the Python Launcher),
    not `python`. Use `py` in all commands below if `python` is not recognized.
- **Administrator PowerShell prompt**
- **NSSM** *(optional)* — [nssm.cc/download](https://nssm.cc/download) — free tool to run
  the server as a persistent Windows Service that survives reboots. Not required if you
  prefer to start the server manually. If installed, place `nssm.exe` in
  `C:\Windows\System32\` so `setup-windows.ps1` can find it automatically.

### Setup

```powershell
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

The script:
1. Verifies Python 3 is installed
2. Installs Flask via `pip`
3. Creates the `files\` directory for uploaded packages
4. Opens port 8080 in Windows Firewall
5. If NSSM is on the PATH: registers and starts a persistent **Windows Service**
6. If NSSM is not present: prints the manual run command (see below)

The server will be available at `http://<server-ip>:8080`.

### Manual run (no NSSM required)

If you don't want to install NSSM, run the server directly from a PowerShell window.
Leave the window open while the server is in use.

> Replace `C:\path\to\Everpure-ZTP` with the actual folder where you extracted the project
> (e.g. `C:\Users\Administrator\Downloads\Everpure-ZTP-main\Everpure-ZTP-main`).

```powershell
cd C:\path\to\Everpure-ZTP
$env:FILE_SERVER_ROOT="C:\path\to\Everpure-ZTP\files"
py app.py
```

> If `py` is not recognized, use the full Python path, e.g.:
> `& "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" app.py`

### Service management (NSSM)

```powershell
nssm stop fileserver
nssm start fileserver
nssm restart fileserver
```

> **Note:** ZTP FlashArray Install and Initialize work fully on Windows. The DHCP Server
> feature requires direct Linux host networking and is not available on Windows.

---

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

- **Endpoint used:** `PATCH http://<ct1.eth1 IP>:8081/array-purity-installations`
- **Required inputs:**
  - `ct1.eth1 ZTP IP` — The DHCP-assigned IP address of ct1.eth1 on the array
  - `.ppkg URL` — Full URL to the Purity package file (use **Copy Link** on a file in the UI)
  - `.ppkg.sig URL` — Full URL to the matching signature file
- **Optional:** DNS nameservers, search domain, and domain can be configured if package URLs use hostnames

The status panel shows live install progress through these phases:

`Not Started` → `Install In Progress` → `Downloading` → `CT0 Installing` → `CT1 Installing` → `Complete`

Clicking **Check Status** automatically polls every 15 seconds until the status reaches `Complete`. The button changes to **Stop Auto-Refresh** while polling is active; click it again to stop.

## ZTP PureInitialize

Sends the initial configuration to a factory-fresh FlashArray.

- **Endpoint used:** `PATCH http://<ct1.eth0 IP>:8081/array-initial-config`
- **Required inputs:**
  - `ct1.eth0 Management IP` — the DHCP-assigned management address after Purity FA is running (not the eth1/eth5 ZTP service address used during software install)
  - FlashArray name
  - IP / Netmask / Gateway for `ct0.eth0`, `ct1.eth0`, and `vir0`
  - NTP servers and timezone
  - EULA acceptance (full name, job title, organization)
- **Optional:** DNS (domain + nameservers), SMTP relay, alert email addresses, **Skip Connectivity Tests** (check this for isolated environments with no internet connectivity — adds `skip_connectivity_tests: true` to the payload)

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

### Copy Link IP Override

If your server has two network interfaces (e.g. a management NIC and a separate ZTP/DHCP NIC), the Copy Link URL defaults to the IP your browser is connected to — which may not be reachable by the FlashArray. Use the **Copy Link IP Override** field in the Files action bar to set the IP of the interface connected to the FlashArray network. All Copy Link URLs will use that IP instead. The value is saved in browser localStorage and persists across page loads.

> **Note:** The `files/` directory is excluded from this repository (`.gitignore`) due to the large size of Purity `.ppkg` firmware bundles (~5–6 GB each).

## ZTE FlashArray Erasure

Drives the full Zero Touch Erasure (ZTE) workflow to securely wipe a FlashArray and return it to a factory-fresh, ZTP-redeployable state. Requires Purity//FA 6.6.8 or later.

> **Destructive operation:** ZTE permanently erases all data and configuration. Complete the pre-erasure checklist displayed in the UI before starting.

### Pre-erasure checklist (required before ZTE will succeed)

The ZTE start request will fail immediately if any of these conditions are not met:

- **Disable SafeMode** — must be off before ZTE can proceed
- **Disconnect all hosts** — remove host connections and host entries
- **Delete and eradicate all volumes and snapshots** (excluding system volumes)
- **Delete and eradicate all protection groups (pgroups)** and pgroup snapshots
- **Delete and eradicate all pods**
- **Remove all array connections** — replication and pod stretch targets
- **Remove offload targets** — NFS, S3, Azure
- **Delete file systems, shares, directory services, and Active Directory configuration**
- **Confirm authorization and business approval**

> Deletion alone is not enough — volumes, snapshots, pgroups, and pods must be explicitly **eradicated** (not just deleted) before ZTE will proceed.

### Workflow

**Phase 1 — Start the secure wipe**

1. Enter the Array Management VIP, API Version (default `2.56`), and API Token, then click **Authenticate** to obtain a session token.
2. Select **Dark-site array** if the array cannot reach Pure Storage for the phone-home check.
3. Click **Start ZTE Wipe** — confirm the prompt. The array begins wiping all drives and generating a sanitization certificate (~30 minutes).
4. Click **Check Wipe Status** — auto-refreshes every 30 seconds. Status progresses to `waiting_for_finalize` when Phase 1 is complete.
5. When status is `waiting_for_finalize`, use **Copy Certificate** or **Download Certificate** to save the sanitization certificate to a secure location before finalizing.

**Phase 2 — Finalize and reinstall**

1. Select image source: **Phoning-home** (`image_source: auto`) or **Dark-site** (provide a URL or `file:///` path to the ZTE image bundle).
2. Click **Finalize & Reinstall Image** — confirm the certificate has been saved. The array reinstalls the Purity image (~40 minutes). The REST API will be unavailable during this phase.
3. After reinstallation, verify the array is in an uninitialized state and the ZTP endpoint responds. Proceed with ZTP PureSoftwareInstall and ZTP PureInitialize as needed.

- **Endpoint used:** `https://<array-mgmt-vip>/api/<version>/arrays/erasures`
- **Cancel ZTE:** Click **Cancel ZTE** to send `DELETE /arrays/erasures` if the operation needs to be aborted.

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
