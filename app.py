#!/usr/bin/env python3
"""Simple file server with upload, download, delete, and folder creation."""

import os
import json
import shutil
import urllib.request
import urllib.parse
import urllib.error
import ssl
from pathlib import Path
from flask import (
    Flask, request, send_from_directory, redirect, url_for,
    render_template_string, flash, abort, jsonify
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

_zte_ssl = ssl.create_default_context()
_zte_ssl.check_hostname = False
_zte_ssl.verify_mode = ssl.CERT_NONE

BASE_DIR = Path(os.environ.get("FILE_SERVER_ROOT", "/home/atcadmin/fileserver/files"))

# Redirect Werkzeug upload temp files away from /tmp (which is a small tmpfs)
# so large .ppkg uploads don't fill the system temp filesystem.
import tempfile
_upload_tmp = BASE_DIR / ".tmp"
_upload_tmp.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(_upload_tmp)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zero Touch Provisioning (ZTP) for FlashArray and FlashBlade</title>
<link href="/logos/bootstrap.min.css" rel="stylesheet">
<link href="/logos/bootstrap-icons.min.css" rel="stylesheet">
<style>
  body { background: #f8f9fa; }
  .file-row:hover { background: #e9ecef; }
  .breadcrumb-item + .breadcrumb-item::before { content: "/"; }
  .action-btn { white-space: nowrap; }
</style>
</head>
<body>
<div class="container-lg py-4">

  <!-- Header -->
  <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-3">
    <div class="d-flex align-items-center gap-3">
      <img src="/logos/everpure.png" alt="Everpure" style="height:48px;object-fit:contain">
      <div>
        <h1 class="h4 mb-0 fw-bold">Zero Touch Provisioning (ZTP)</h1>
        <div class="text-muted small">for FlashArray and FlashBlade</div>
      </div>
    </div>
    <img src="/logos/wwtlogo.png" alt="WWT" style="height:40px;object-fit:contain">
  </div>

  <!-- Flash messages -->
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="alert alert-{{ 'danger' if cat == 'error' else 'success' }} alert-dismissible fade show" role="alert">
        {{ msg }}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      </div>
    {% endfor %}
  {% endwith %}

  <!-- Breadcrumb -->
  <nav aria-label="breadcrumb" class="mb-3">
    <ol class="breadcrumb bg-white border rounded px-3 py-2">
      <li class="breadcrumb-item">
        <a href="{{ url_for('index', subpath='') }}"><i class="bi bi-house-door"></i> Root</a>
      </li>
      {% for part in breadcrumbs %}
      <li class="breadcrumb-item {% if loop.last %}active{% endif %}">
        {% if not loop.last %}
          <a href="{{ url_for('index', subpath=part.path) }}">{{ part.name }}</a>
        {% else %}
          {{ part.name }}
        {% endif %}
      </li>
      {% endfor %}
    </ol>
  </nav>

  <!-- Action bar -->
  <div class="card mb-3">
    <div class="card-body">
      <div class="row g-3 align-items-end">

        <!-- Upload -->
        <div class="col-md-5">
          <form method="POST" action="{{ url_for('upload', subpath=current_path) }}" enctype="multipart/form-data">
            <label class="form-label fw-semibold mb-1"><i class="bi bi-upload"></i> Upload Files</label>
            <div class="input-group">
              <input type="file" name="files" class="form-control" multiple required>
              <button class="btn btn-primary" type="submit">Upload</button>
            </div>
          </form>
        </div>

        <!-- Create folder -->
        <div class="col-md-4">
          <form method="POST" action="{{ url_for('mkdir', subpath=current_path) }}">
            <label class="form-label fw-semibold mb-1"><i class="bi bi-folder-plus"></i> New Folder</label>
            <div class="input-group">
              <input type="text" name="folder_name" class="form-control" placeholder="Folder name" required pattern="[^/\\\\&lt;&gt;:&quot;|?*]+" title="No special characters">
              <button class="btn btn-success" type="submit">Create</button>
            </div>
          </form>
        </div>

        <!-- Fetch from URL -->
        <div class="col-12">
          <form method="POST" action="{{ url_for('fetch_url', subpath=current_path) }}">
            <label class="form-label fw-semibold mb-1"><i class="bi bi-cloud-download"></i> Fetch from URL</label>
            <div class="input-group">
              <input type="url" name="url" class="form-control" placeholder="https://example.com/firmware.bin" required>
              <button class="btn btn-warning" type="submit">Fetch</button>
            </div>
          </form>
        </div>

        <!-- Copy Link IP override -->
        <div class="col-12">
          <label class="form-label fw-semibold mb-1">
            <i class="bi bi-link-45deg"></i> Copy Link IP Override
            <span class="text-muted fw-normal ms-1" style="font-size:0.85rem">
              — Set this to the IP of the interface connected to the FlashArray network if your
              server has multiple NICs (e.g. a separate ZTP / DHCP interface). Leave blank to
              use the IP you are currently connected to.
            </span>
          </label>
          <div class="input-group" style="max-width:360px">
            <span class="input-group-text"><i class="bi bi-hdd-network"></i></span>
            <input type="text" id="copyLinkIpOverride" class="form-control"
                   placeholder="e.g. 192.168.10.5"
                   oninput="saveCopyLinkIp(this.value)">
            <button class="btn btn-outline-secondary" type="button" onclick="clearCopyLinkIp()">Clear</button>
          </div>
        </div>

      </div>
    </div>
  </div>

  <!-- File listing -->
  <div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span class="fw-semibold">
        <i class="bi bi-folder2-open me-1"></i>
        {{ current_path or '/' }}
      </span>
      <small class="text-muted">{{ entries|length }} item(s)</small>
    </div>
    <div class="list-group list-group-flush">

      {% if current_path %}
      <div class="list-group-item file-row">
        <a href="{{ url_for('index', subpath=parent_path) }}" class="text-decoration-none">
          <i class="bi bi-arrow-up-circle text-secondary me-2"></i>
          <span class="text-secondary">.. (parent directory)</span>
        </a>
      </div>
      {% endif %}

      {% if not entries %}
      <div class="list-group-item text-muted fst-italic">
        <i class="bi bi-inbox me-2"></i>This folder is empty.
      </div>
      {% endif %}

      {% for entry in entries %}
      <div class="list-group-item file-row d-flex justify-content-between align-items-center py-2">
        <div class="d-flex align-items-center gap-2 text-truncate me-3">
          {% if entry.is_dir %}
            <i class="bi bi-folder-fill text-warning fs-5"></i>
            <a href="{{ url_for('index', subpath=entry.rel_path) }}" class="text-decoration-none fw-medium">
              {{ entry.name }}
            </a>
          {% else %}
            <i class="bi bi-file-earmark text-secondary fs-5"></i>
            <span>{{ entry.name }}</span>
            <small class="text-muted">{{ entry.size }}</small>
          {% endif %}
        </div>

        <div class="d-flex gap-2 action-btn flex-shrink-0">
          {% if not entry.is_dir %}
          <a href="{{ url_for('download', subpath=entry.rel_path) }}"
             class="btn btn-sm btn-outline-primary">
            <i class="bi bi-download"></i> Download
          </a>
          <button class="btn btn-sm btn-outline-secondary"
                  onclick="copyLink(this, '{{ entry.rel_path }}')">
            <i class="bi bi-clipboard"></i> Copy Link
          </button>
          <button class="btn btn-sm btn-outline-secondary"
                  onclick="openMoveModal('{{ entry.rel_path }}', '{{ entry.name }}')">
            <i class="bi bi-folder-symlink"></i> Move
          </button>
          {% endif %}
          <form method="POST" action="{{ url_for('delete', subpath=entry.rel_path) }}"
                onsubmit="return confirm('Delete {{ entry.name }}?')">
            <button class="btn btn-sm btn-outline-danger" type="submit">
              <i class="bi bi-trash"></i> Delete
            </button>
          </form>
        </div>
      </div>
      {% endfor %}

    </div>
  </div>

<!-- DHCP Server -->
<div class="card mt-3">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#dhcpCollapse">
    <span class="fw-semibold"><i class="bi bi-router text-success me-1"></i> DHCP Server</span>
    <span id="dhcpHeaderBadge"></span>
    <i class="bi bi-chevron-down"></i>
  </div>
  <div class="collapse" id="dhcpCollapse">
    <div class="card-body">

      <div class="alert alert-info py-2 mb-2">
        <i class="bi bi-info-circle-fill me-1"></i>
        <strong>Linux VM installs only.</strong> The DHCP server requires direct access to the host network interface and will not function when running inside a Docker container on macOS or Windows. Use this feature only when the application is installed directly on a Linux VM or bare-metal host.
      </div>
      <div class="alert alert-warning py-2 mb-3">
        <i class="bi bi-exclamation-triangle-fill me-1"></i>
        <strong>Warning:</strong> Only enable on isolated private networks. A DHCP server on a shared network will conflict with existing DHCP servers and disrupt other clients.
      </div>

      <!-- Status bar -->
      <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
        <span class="fw-semibold">Status:</span>
        <span id="dhcpStatusBadge" class="badge fs-6 bg-secondary">Loading...</span>
        <button class="btn btn-sm btn-outline-secondary" onclick="loadDhcpInterfaces(); loadDhcpStatus();">
          <i class="bi bi-arrow-clockwise me-1"></i> Refresh
        </button>
        <button class="btn btn-sm btn-outline-warning fw-semibold" id="dhcpRestartBtn"
                onclick="dhcpRestart(this)" style="display:none">
          <i class="bi bi-arrow-repeat me-1"></i> Restart DHCP
        </button>
      </div>

      <!-- Config form -->
      <div id="dhcpConfigForm">
        <div class="row g-3">
          <div class="col-md-4">
            <label class="form-label fw-semibold">Network Interface</label>
            <select id="dhcpIface" class="form-select" onchange="updateIfaceIpDisplay()">
              <option value="">Loading interfaces…</option>
            </select>
            <div id="dhcpIfaceIpDisplay" class="form-text mt-1"></div>
          </div>
          <div class="col-md-4">
            <label class="form-label fw-semibold">Subnet</label>
            <input type="text" id="dhcpSubnet" class="form-control" placeholder="192.168.1.0/24" value="192.168.1.0/24">
          </div>
          <div class="col-md-2">
            <label class="form-label fw-semibold">Range Start</label>
            <input type="text" id="dhcpRangeStart" class="form-control" placeholder="192.168.1.11" value="192.168.1.11">
          </div>
          <div class="col-md-2">
            <label class="form-label fw-semibold">Range End</label>
            <input type="text" id="dhcpRangeEnd" class="form-control" placeholder="192.168.1.30" value="192.168.1.30">
          </div>
          <div class="col-md-4">
            <label class="form-label fw-semibold">Server IP Address <small class="text-muted fw-normal">— CIDR notation</small></label>
            <input type="text" id="dhcpServerIp" class="form-control" placeholder="192.168.1.1/24" value="192.168.1.1/24">
            <div class="form-text">Assigned to the selected interface on start, removed on stop.</div>
          </div>
          <div class="col-12">
            <div class="form-text"><i class="bi bi-clock me-1"></i>Lease time is fixed at <strong>60 minutes</strong>.</div>
          </div>
          <div class="col-12">
            <button class="btn btn-success fw-semibold" id="dhcpStartBtn" onclick="dhcpStart(this)">
              <i class="bi bi-play-fill me-1"></i> Enable DHCP Server
            </button>
            <button class="btn btn-danger fw-semibold ms-2" id="dhcpStopBtn" onclick="dhcpStop(this)" style="display:none">
              <i class="bi bi-stop-fill me-1"></i> Disable DHCP Server
            </button>
          </div>
        </div>
      </div>

      <!-- Active leases -->
      <div class="mt-3">
        <button class="btn btn-outline-secondary btn-sm fw-semibold" onclick="loadDhcpLeases(this)">
          <i class="bi bi-table me-1"></i> Show Active Leases
        </button>
        <button class="btn btn-outline-secondary btn-sm fw-semibold ms-2" onclick="loadDhcpLogs(this)">
          <i class="bi bi-terminal me-1"></i> Show Logs
        </button>
        <div id="dhcpLeasesPanel" class="mt-2 d-none">
          <hr>
          <p class="fw-semibold mb-2">Active DHCP Leases</p>
          <div class="table-responsive">
            <table class="table table-sm table-bordered align-middle mb-0">
              <thead class="table-dark">
                <tr>
                  <th>IP Address</th>
                  <th>MAC Address</th>
                  <th>Hostname</th>
                  <th>Lease Expiry</th>
                </tr>
              </thead>
              <tbody id="dhcpLeasesBody">
                <tr><td colspan="4" class="text-muted fst-italic text-center">No leases found.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <div id="dhcpLogsPanel" class="mt-2 d-none">
          <hr>
          <p class="fw-semibold mb-2">dnsmasq Logs <small class="text-muted fw-normal">(last 100 lines)</small></p>
          <pre id="dhcpLogsBody" class="bg-dark text-light rounded p-3"
               style="max-height:300px;overflow:auto;font-size:0.8rem;white-space:pre-wrap">(no log output)</pre>
        </div>
      </div>

    </div>
  </div>
</div>

<!-- ZTP FlashArray Install -->
<div class="card mt-3">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#ztpInstall">
    <span class="fw-semibold"><i class="bi bi-lightning-charge text-warning me-1"></i> ZTP FlashArray Install</span>
    <i class="bi bi-chevron-down"></i>
  </div>
  <div class="collapse" id="ztpInstall">
    <div class="card-body">
      <p class="text-muted small mb-3">
        <i class="bi bi-info-circle me-1"></i>
        Starts a Purity installation on an array via ZTP. Use <strong>Copy Link</strong> on files above to get .ppkg / .ppkg.sig URLs served from this server.
      </p>
      <div class="row g-3">
        <div class="col-md-4">
          <label class="form-label fw-semibold">Controller 1 (bottom controller) eth1/eth5 ZTP IP</label>
          <input type="text" id="ztpIp" class="form-control" placeholder="192.168.1.100">
          <div class="form-text">Port 8081 is used automatically. From a console connection, look for it under <code>ps_eth1@br_eth1</code> (or <code>5</code>) when running <code>ip a</code>.</div>
        </div>
        <div class="col-md-8">
          <label class="form-label fw-semibold">Package Path <small class="text-muted fw-normal">— .ppkg file URL</small></label>
          <input type="text" id="ztpPkg" class="form-control font-monospace"
                 placeholder="http://192.0.2.10/purity_6.9.0_....ppkg">
        </div>
        <div class="col-md-8 offset-md-4">
          <label class="form-label fw-semibold">Signature File Path <small class="text-muted fw-normal">— .ppkg.sig file URL</small></label>
          <input type="text" id="ztpSig" class="form-control font-monospace"
                 placeholder="http://192.0.2.10/purity_6.9.0_....ppkg.sig">
          <div class="form-text text-warning">
            <i class="bi bi-exclamation-triangle me-1"></i>.ppkg and .ppkg.sig must be from the same GA release.
          </div>
        </div>

        <div class="col-12">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="ztpDnsEnabled"
                   onchange="document.getElementById('ztpDnsFields').classList.toggle('d-none',!this.checked)">
            <label class="form-check-label fw-semibold" for="ztpDnsEnabled">
              Configure DNS <small class="text-muted fw-normal">— required when package URLs use hostnames</small>
            </label>
          </div>
        </div>
        <div id="ztpDnsFields" class="col-12 d-none">
          <div class="row g-3">
            <div class="col-md-5">
              <label class="form-label fw-semibold">Nameservers <small class="text-muted fw-normal">— comma-separated</small></label>
              <input type="text" id="ztpNs" class="form-control" placeholder="192.0.2.10, 198.51.100.25">
            </div>
            <div class="col-md-4">
              <label class="form-label fw-semibold">Search</label>
              <input type="text" id="ztpSearch" class="form-control" placeholder="dev.purestorage.com">
            </div>
            <div class="col-md-3">
              <label class="form-label fw-semibold">Domain</label>
              <input type="text" id="ztpDomain" class="form-control" placeholder="dev.purestorage.com">
            </div>
          </div>
        </div>

        <div class="col-12 d-flex gap-2 flex-wrap">
          <button class="btn btn-warning fw-semibold" onclick="runZtpInstall(this)">
            <i class="bi bi-lightning-charge-fill me-1"></i> Start PureInstall
          </button>
          <button id="ztpStatusBtn" class="btn btn-outline-secondary fw-semibold" onclick="runZtpStatus(this)">
            <i class="bi bi-arrow-clockwise me-1"></i> Check Status
          </button>
        </div>
      </div>

      <!-- Install response -->
      <div id="ztpResponse" class="mt-3 d-none">
        <hr>
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="fw-semibold">Install Response</span>
          <span id="ztpStatusBadge" class="badge fs-6"></span>
        </div>
        <pre id="ztpResponseBody" class="bg-dark text-light rounded p-3"
             style="max-height:300px;overflow:auto;font-size:0.85rem;white-space:pre-wrap"></pre>
      </div>

      <!-- Status panel -->
      <div id="ztpStatusPanel" class="mt-3 d-none">
        <hr>
        <div class="d-flex align-items-center gap-2 mb-3">
          <span class="fw-semibold">Install Status</span>
          <span id="ztpPhaseBadge" class="badge fs-6"></span>
        </div>
        <div id="ztpPhaseDesc" class="text-muted small mb-3"></div>
        <div class="d-flex flex-wrap gap-2 mb-3" id="ztpSteps"></div>
        <div id="ztpErrorsBlock" class="d-none">
          <p class="fw-semibold text-danger mb-1"><i class="bi bi-x-circle me-1"></i>Errors</p>
          <pre id="ztpErrorsBody" class="bg-danger bg-opacity-10 border border-danger rounded p-2"
               style="font-size:0.85rem;white-space:pre-wrap"></pre>
        </div>
        <div id="ztpCompleteNote" class="alert alert-success d-none">
          <i class="bi bi-check-circle me-1"></i>
          <strong>install-complete</strong> — both controllers have rebooted. Verify the final version with
          <code>pureversion -a</code> once Purity is up.
        </div>
      </div>
    </div>
  </div>
</div>


<!-- ZTP FlashArray Initialize -->
<div class="card mt-3">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#ztpInitCollapse">
    <span class="fw-semibold"><i class="bi bi-hdd-rack text-info me-1"></i> ZTP FlashArray Initialize</span>
    <i class="bi bi-chevron-down"></i>
  </div>
  <div class="collapse" id="ztpInitCollapse">
    <div class="card-body">
      <p class="text-muted small mb-3">
        <i class="bi bi-info-circle me-1"></i>
        Sends initial configuration to a FlashArray via a PATCH request to <code>http://[ct1.eth0 IP]:8081/array-initial-config</code>. Use this after ZTP PureSoftwareInstall completes — Purity FA is now running and the ZTP service is no longer active.
      </p>
      <div class="alert alert-info py-2 small mb-3">
        <i class="bi bi-exclamation-circle me-1"></i>
        <strong>RC4 arrays</strong> using ETH4/5 as management ports: select <strong>ETH4 / VIR4</strong> below.
      </div>
      <div class="row g-3">

        <!-- Import JSON -->
        <div class="col-12">
          <label class="form-label fw-semibold"><i class="bi bi-file-earmark-arrow-up me-1"></i> Import from JSON</label>
          <input type="file" id="initImportFile" class="form-control" accept=".json,application/json" onchange="importInitPayload(this)">
          <div class="form-text">Import a previously downloaded initialize-config JSON to pre-fill the form fields below.</div>
        </div>

        <!-- Target IP and Interface Mode -->
        <div class="col-md-4">
          <label class="form-label fw-semibold">Controller 1 (bottom controller) eth0/eth4 Management IP</label>
          <input type="text" id="initIp" class="form-control" placeholder="192.168.1.100">
          <div class="form-text">DHCP-assigned management IP — not the eth1/eth5 ZTP service address. Port 8081 is used automatically. From a console connection, look for it under <code>ps_eth0@br_eth0</code> (or <code>4</code>) when running <code>ip a</code>.</div>
        </div>
        <div class="col-md-4 d-flex align-items-end pb-1">
          <div>
            <label class="form-label fw-semibold d-block">Interface Mode
              <small class="text-muted fw-normal ms-1">— FlashArray //X, //C, //E typically ETH4/VIR4 &nbsp;|&nbsp; FlashArray //XL typically ETH0/VIR0</small>
            </label>
            <div class="btn-group" role="group">
              <input type="radio" class="btn-check" name="initIfaceMode" id="initModeEth0" value="0" checked onchange="updateInitLabels()">
              <label class="btn btn-outline-secondary" for="initModeEth0">ETH0 / VIR0</label>
              <input type="radio" class="btn-check" name="initIfaceMode" id="initModeEth4" value="4" onchange="updateInitLabels()">
              <label class="btn btn-outline-secondary" for="initModeEth4">ETH4 / VIR4</label>
            </div>
          </div>
        </div>
        <div class="col-md-4">
          <label class="form-label fw-semibold">FlashArray Name</label>
          <input type="text" id="initArrayName" class="form-control" placeholder="my-flasharray-01">
        </div>

        <!-- ct0.ethX -->
        <div class="col-12">
          <label class="form-label fw-semibold" id="initCt0Label">ct0.eth0</label>
          <div class="row g-2">
            <div class="col-md-4"><input type="text" id="initCt0Addr" class="form-control" placeholder="IP Address"></div>
            <div class="col-md-4"><input type="text" id="initCt0Mask" class="form-control" placeholder="Netmask (255.255.255.0)"></div>
            <div class="col-md-4"><input type="text" id="initCt0Gw"   class="form-control" placeholder="Gateway"></div>
          </div>
        </div>

        <!-- ct1.ethX -->
        <div class="col-12">
          <label class="form-label fw-semibold" id="initCt1Label">ct1.eth0</label>
          <div class="row g-2">
            <div class="col-md-4"><input type="text" id="initCt1Addr" class="form-control" placeholder="IP Address"></div>
            <div class="col-md-4"><input type="text" id="initCt1Mask" class="form-control" placeholder="Netmask (255.255.255.0)"></div>
            <div class="col-md-4"><input type="text" id="initCt1Gw"   class="form-control" placeholder="Gateway"></div>
          </div>
        </div>

        <!-- virX -->
        <div class="col-12">
          <label class="form-label fw-semibold" id="initVirLabel">vir0</label>
          <div class="row g-2">
            <div class="col-md-4"><input type="text" id="initVirAddr" class="form-control" placeholder="IP Address"></div>
            <div class="col-md-4"><input type="text" id="initVirMask" class="form-control" placeholder="Netmask (255.255.255.0)"></div>
            <div class="col-md-4"><input type="text" id="initVirGw"   class="form-control" placeholder="Gateway"></div>
          </div>
        </div>

        <!-- NTP + Timezone -->
        <div class="col-md-7">
          <label class="form-label fw-semibold">NTP Servers <small class="text-muted fw-normal">— comma-separated</small></label>
          <input type="text" id="initNtp" class="form-control" placeholder="time1.purestorage.com, pool.ntp.org">
        </div>
        <div class="col-md-5">
          <label class="form-label fw-semibold">Time Zone</label>
          <input type="text" id="initTz" class="form-control" placeholder="America/Chicago" list="tzList" autocomplete="off">
          <datalist id="tzList">
            <option value="Africa/Abidjan">
            <option value="Africa/Accra">
            <option value="Africa/Addis_Ababa">
            <option value="Africa/Algiers">
            <option value="Africa/Asmara">
            <option value="Africa/Bamako">
            <option value="Africa/Bangui">
            <option value="Africa/Banjul">
            <option value="Africa/Bissau">
            <option value="Africa/Blantyre">
            <option value="Africa/Brazzaville">
            <option value="Africa/Bujumbura">
            <option value="Africa/Cairo">
            <option value="Africa/Casablanca">
            <option value="Africa/Ceuta">
            <option value="Africa/Conakry">
            <option value="Africa/Dakar">
            <option value="Africa/Dar_es_Salaam">
            <option value="Africa/Djibouti">
            <option value="Africa/Douala">
            <option value="Africa/El_Aaiun">
            <option value="Africa/Freetown">
            <option value="Africa/Gaborone">
            <option value="Africa/Harare">
            <option value="Africa/Johannesburg">
            <option value="Africa/Juba">
            <option value="Africa/Kampala">
            <option value="Africa/Khartoum">
            <option value="Africa/Kigali">
            <option value="Africa/Kinshasa">
            <option value="Africa/Lagos">
            <option value="Africa/Libreville">
            <option value="Africa/Lome">
            <option value="Africa/Luanda">
            <option value="Africa/Lubumbashi">
            <option value="Africa/Lusaka">
            <option value="Africa/Malabo">
            <option value="Africa/Maputo">
            <option value="Africa/Maseru">
            <option value="Africa/Mbabane">
            <option value="Africa/Mogadishu">
            <option value="Africa/Monrovia">
            <option value="Africa/Nairobi">
            <option value="Africa/Ndjamena">
            <option value="Africa/Niamey">
            <option value="Africa/Nouakchott">
            <option value="Africa/Ouagadougou">
            <option value="Africa/Porto-Novo">
            <option value="Africa/Sao_Tome">
            <option value="Africa/Tripoli">
            <option value="Africa/Tunis">
            <option value="Africa/Windhoek">
            <option value="America/Adak">
            <option value="America/Anchorage">
            <option value="America/Anguilla">
            <option value="America/Antigua">
            <option value="America/Araguaina">
            <option value="America/Argentina/Buenos_Aires">
            <option value="America/Argentina/Catamarca">
            <option value="America/Argentina/Cordoba">
            <option value="America/Argentina/Jujuy">
            <option value="America/Argentina/La_Rioja">
            <option value="America/Argentina/Mendoza">
            <option value="America/Argentina/Rio_Gallegos">
            <option value="America/Argentina/Salta">
            <option value="America/Argentina/San_Juan">
            <option value="America/Argentina/San_Luis">
            <option value="America/Argentina/Tucuman">
            <option value="America/Argentina/Ushuaia">
            <option value="America/Aruba">
            <option value="America/Asuncion">
            <option value="America/Atikokan">
            <option value="America/Bahia">
            <option value="America/Bahia_Banderas">
            <option value="America/Barbados">
            <option value="America/Belem">
            <option value="America/Belize">
            <option value="America/Blanc-Sablon">
            <option value="America/Boa_Vista">
            <option value="America/Bogota">
            <option value="America/Boise">
            <option value="America/Cambridge_Bay">
            <option value="America/Campo_Grande">
            <option value="America/Cancun">
            <option value="America/Caracas">
            <option value="America/Cayenne">
            <option value="America/Cayman">
            <option value="America/Chicago">
            <option value="America/Chihuahua">
            <option value="America/Ciudad_Juarez">
            <option value="America/Costa_Rica">
            <option value="America/Coyhaique">
            <option value="America/Creston">
            <option value="America/Cuiaba">
            <option value="America/Curacao">
            <option value="America/Danmarkshavn">
            <option value="America/Dawson">
            <option value="America/Dawson_Creek">
            <option value="America/Denver">
            <option value="America/Detroit">
            <option value="America/Dominica">
            <option value="America/Edmonton">
            <option value="America/Eirunepe">
            <option value="America/El_Salvador">
            <option value="America/Fort_Nelson">
            <option value="America/Fortaleza">
            <option value="America/Glace_Bay">
            <option value="America/Goose_Bay">
            <option value="America/Grand_Turk">
            <option value="America/Grenada">
            <option value="America/Guadeloupe">
            <option value="America/Guatemala">
            <option value="America/Guayaquil">
            <option value="America/Guyana">
            <option value="America/Halifax">
            <option value="America/Havana">
            <option value="America/Hermosillo">
            <option value="America/Indiana/Indianapolis">
            <option value="America/Indiana/Knox">
            <option value="America/Indiana/Marengo">
            <option value="America/Indiana/Petersburg">
            <option value="America/Indiana/Tell_City">
            <option value="America/Indiana/Vevay">
            <option value="America/Indiana/Vincennes">
            <option value="America/Indiana/Winamac">
            <option value="America/Inuvik">
            <option value="America/Iqaluit">
            <option value="America/Jamaica">
            <option value="America/Juneau">
            <option value="America/Kentucky/Louisville">
            <option value="America/Kentucky/Monticello">
            <option value="America/Kralendijk">
            <option value="America/La_Paz">
            <option value="America/Lima">
            <option value="America/Los_Angeles">
            <option value="America/Lower_Princes">
            <option value="America/Maceio">
            <option value="America/Managua">
            <option value="America/Manaus">
            <option value="America/Marigot">
            <option value="America/Martinique">
            <option value="America/Matamoros">
            <option value="America/Mazatlan">
            <option value="America/Menominee">
            <option value="America/Merida">
            <option value="America/Metlakatla">
            <option value="America/Mexico_City">
            <option value="America/Miquelon">
            <option value="America/Moncton">
            <option value="America/Monterrey">
            <option value="America/Montevideo">
            <option value="America/Montserrat">
            <option value="America/Nassau">
            <option value="America/New_York">
            <option value="America/Nome">
            <option value="America/Noronha">
            <option value="America/North_Dakota/Beulah">
            <option value="America/North_Dakota/Center">
            <option value="America/North_Dakota/New_Salem">
            <option value="America/Nuuk">
            <option value="America/Ojinaga">
            <option value="America/Panama">
            <option value="America/Paramaribo">
            <option value="America/Phoenix">
            <option value="America/Port-au-Prince">
            <option value="America/Port_of_Spain">
            <option value="America/Porto_Velho">
            <option value="America/Puerto_Rico">
            <option value="America/Punta_Arenas">
            <option value="America/Rankin_Inlet">
            <option value="America/Recife">
            <option value="America/Regina">
            <option value="America/Resolute">
            <option value="America/Rio_Branco">
            <option value="America/Santarem">
            <option value="America/Santiago">
            <option value="America/Santo_Domingo">
            <option value="America/Sao_Paulo">
            <option value="America/Scoresbysund">
            <option value="America/Sitka">
            <option value="America/St_Barthelemy">
            <option value="America/St_Johns">
            <option value="America/St_Kitts">
            <option value="America/St_Lucia">
            <option value="America/St_Thomas">
            <option value="America/St_Vincent">
            <option value="America/Swift_Current">
            <option value="America/Tegucigalpa">
            <option value="America/Thule">
            <option value="America/Thunder_Bay">
            <option value="America/Tijuana">
            <option value="America/Toronto">
            <option value="America/Tortola">
            <option value="America/Vancouver">
            <option value="America/Whitehorse">
            <option value="America/Winnipeg">
            <option value="America/Yakutat">
            <option value="America/Yellowknife">
            <option value="Antarctica/Casey">
            <option value="Antarctica/Davis">
            <option value="Antarctica/DumontDUrville">
            <option value="Antarctica/Macquarie">
            <option value="Antarctica/Mawson">
            <option value="Antarctica/McMurdo">
            <option value="Antarctica/Palmer">
            <option value="Antarctica/Rothera">
            <option value="Antarctica/Syowa">
            <option value="Antarctica/Troll">
            <option value="Antarctica/Vostok">
            <option value="Arctic/Longyearbyen">
            <option value="Asia/Aden">
            <option value="Asia/Almaty">
            <option value="Asia/Amman">
            <option value="Asia/Anadyr">
            <option value="Asia/Aqtau">
            <option value="Asia/Aqtobe">
            <option value="Asia/Ashgabat">
            <option value="Asia/Atyrau">
            <option value="Asia/Baghdad">
            <option value="Asia/Bahrain">
            <option value="Asia/Baku">
            <option value="Asia/Bangkok">
            <option value="Asia/Barnaul">
            <option value="Asia/Beirut">
            <option value="Asia/Bishkek">
            <option value="Asia/Brunei">
            <option value="Asia/Chita">
            <option value="Asia/Choibalsan">
            <option value="Asia/Colombo">
            <option value="Asia/Damascus">
            <option value="Asia/Dhaka">
            <option value="Asia/Dili">
            <option value="Asia/Dubai">
            <option value="Asia/Dushanbe">
            <option value="Asia/Famagusta">
            <option value="Asia/Gaza">
            <option value="Asia/Hebron">
            <option value="Asia/Ho_Chi_Minh">
            <option value="Asia/Hong_Kong">
            <option value="Asia/Hovd">
            <option value="Asia/Irkutsk">
            <option value="Asia/Jakarta">
            <option value="Asia/Jayapura">
            <option value="Asia/Jerusalem">
            <option value="Asia/Kabul">
            <option value="Asia/Kamchatka">
            <option value="Asia/Karachi">
            <option value="Asia/Kathmandu">
            <option value="Asia/Khandyga">
            <option value="Asia/Kolkata">
            <option value="Asia/Krasnoyarsk">
            <option value="Asia/Kuala_Lumpur">
            <option value="Asia/Kuching">
            <option value="Asia/Kuwait">
            <option value="Asia/Macau">
            <option value="Asia/Magadan">
            <option value="Asia/Makassar">
            <option value="Asia/Manila">
            <option value="Asia/Muscat">
            <option value="Asia/Nicosia">
            <option value="Asia/Novokuznetsk">
            <option value="Asia/Novosibirsk">
            <option value="Asia/Omsk">
            <option value="Asia/Oral">
            <option value="Asia/Phnom_Penh">
            <option value="Asia/Pontianak">
            <option value="Asia/Pyongyang">
            <option value="Asia/Qatar">
            <option value="Asia/Qostanay">
            <option value="Asia/Qyzylorda">
            <option value="Asia/Riyadh">
            <option value="Asia/Sakhalin">
            <option value="Asia/Samarkand">
            <option value="Asia/Seoul">
            <option value="Asia/Shanghai">
            <option value="Asia/Singapore">
            <option value="Asia/Srednekolymsk">
            <option value="Asia/Taipei">
            <option value="Asia/Tashkent">
            <option value="Asia/Tbilisi">
            <option value="Asia/Tehran">
            <option value="Asia/Thimphu">
            <option value="Asia/Tokyo">
            <option value="Asia/Tomsk">
            <option value="Asia/Ulaanbaatar">
            <option value="Asia/Urumqi">
            <option value="Asia/Ust-Nera">
            <option value="Asia/Vientiane">
            <option value="Asia/Vladivostok">
            <option value="Asia/Yakutsk">
            <option value="Asia/Yangon">
            <option value="Asia/Yekaterinburg">
            <option value="Asia/Yerevan">
            <option value="Atlantic/Azores">
            <option value="Atlantic/Bermuda">
            <option value="Atlantic/Canary">
            <option value="Atlantic/Cape_Verde">
            <option value="Atlantic/Faroe">
            <option value="Atlantic/Madeira">
            <option value="Atlantic/Reykjavik">
            <option value="Atlantic/South_Georgia">
            <option value="Atlantic/St_Helena">
            <option value="Atlantic/Stanley">
            <option value="Australia/Adelaide">
            <option value="Australia/Brisbane">
            <option value="Australia/Broken_Hill">
            <option value="Australia/Darwin">
            <option value="Australia/Eucla">
            <option value="Australia/Hobart">
            <option value="Australia/Lindeman">
            <option value="Australia/Lord_Howe">
            <option value="Australia/Melbourne">
            <option value="Australia/Perth">
            <option value="Australia/Sydney">
            <option value="Etc/GMT">
            <option value="Etc/GMT+1">
            <option value="Etc/GMT+2">
            <option value="Etc/GMT+3">
            <option value="Etc/GMT+4">
            <option value="Etc/GMT+5">
            <option value="Etc/GMT+6">
            <option value="Etc/GMT+7">
            <option value="Etc/GMT+8">
            <option value="Etc/GMT+9">
            <option value="Etc/GMT+10">
            <option value="Etc/GMT+11">
            <option value="Etc/GMT+12">
            <option value="Etc/GMT-1">
            <option value="Etc/GMT-2">
            <option value="Etc/GMT-3">
            <option value="Etc/GMT-4">
            <option value="Etc/GMT-5">
            <option value="Etc/GMT-6">
            <option value="Etc/GMT-7">
            <option value="Etc/GMT-8">
            <option value="Etc/GMT-9">
            <option value="Etc/GMT-10">
            <option value="Etc/GMT-11">
            <option value="Etc/GMT-12">
            <option value="Etc/GMT-13">
            <option value="Etc/GMT-14">
            <option value="Etc/UTC">
            <option value="Europe/Amsterdam">
            <option value="Europe/Andorra">
            <option value="Europe/Astrakhan">
            <option value="Europe/Athens">
            <option value="Europe/Belgrade">
            <option value="Europe/Berlin">
            <option value="Europe/Bratislava">
            <option value="Europe/Brussels">
            <option value="Europe/Bucharest">
            <option value="Europe/Budapest">
            <option value="Europe/Busingen">
            <option value="Europe/Chisinau">
            <option value="Europe/Copenhagen">
            <option value="Europe/Dublin">
            <option value="Europe/Gibraltar">
            <option value="Europe/Guernsey">
            <option value="Europe/Helsinki">
            <option value="Europe/Isle_of_Man">
            <option value="Europe/Istanbul">
            <option value="Europe/Jersey">
            <option value="Europe/Kaliningrad">
            <option value="Europe/Kyiv">
            <option value="Europe/Kirov">
            <option value="Europe/Lisbon">
            <option value="Europe/Ljubljana">
            <option value="Europe/London">
            <option value="Europe/Luxembourg">
            <option value="Europe/Madrid">
            <option value="Europe/Malta">
            <option value="Europe/Mariehamn">
            <option value="Europe/Minsk">
            <option value="Europe/Monaco">
            <option value="Europe/Moscow">
            <option value="Europe/Nicosia">
            <option value="Europe/Oslo">
            <option value="Europe/Paris">
            <option value="Europe/Podgorica">
            <option value="Europe/Prague">
            <option value="Europe/Riga">
            <option value="Europe/Rome">
            <option value="Europe/Samara">
            <option value="Europe/San_Marino">
            <option value="Europe/Sarajevo">
            <option value="Europe/Saratov">
            <option value="Europe/Simferopol">
            <option value="Europe/Skopje">
            <option value="Europe/Sofia">
            <option value="Europe/Stockholm">
            <option value="Europe/Tallinn">
            <option value="Europe/Tirane">
            <option value="Europe/Ulyanovsk">
            <option value="Europe/Uzhgorod">
            <option value="Europe/Vaduz">
            <option value="Europe/Vatican">
            <option value="Europe/Vienna">
            <option value="Europe/Vilnius">
            <option value="Europe/Volgograd">
            <option value="Europe/Warsaw">
            <option value="Europe/Zagreb">
            <option value="Europe/Zaporozhye">
            <option value="Europe/Zurich">
            <option value="Indian/Antananarivo">
            <option value="Indian/Chagos">
            <option value="Indian/Christmas">
            <option value="Indian/Cocos">
            <option value="Indian/Comoro">
            <option value="Indian/Kerguelen">
            <option value="Indian/Mahe">
            <option value="Indian/Maldives">
            <option value="Indian/Mauritius">
            <option value="Indian/Mayotte">
            <option value="Indian/Reunion">
            <option value="Pacific/Apia">
            <option value="Pacific/Auckland">
            <option value="Pacific/Bougainville">
            <option value="Pacific/Chatham">
            <option value="Pacific/Chuuk">
            <option value="Pacific/Easter">
            <option value="Pacific/Efate">
            <option value="Pacific/Fakaofo">
            <option value="Pacific/Fiji">
            <option value="Pacific/Funafuti">
            <option value="Pacific/Galapagos">
            <option value="Pacific/Gambier">
            <option value="Pacific/Guadalcanal">
            <option value="Pacific/Guam">
            <option value="Pacific/Honolulu">
            <option value="Pacific/Kanton">
            <option value="Pacific/Kiritimati">
            <option value="Pacific/Kosrae">
            <option value="Pacific/Kwajalein">
            <option value="Pacific/Majuro">
            <option value="Pacific/Marquesas">
            <option value="Pacific/Midway">
            <option value="Pacific/Nauru">
            <option value="Pacific/Niue">
            <option value="Pacific/Norfolk">
            <option value="Pacific/Noumea">
            <option value="Pacific/Pago_Pago">
            <option value="Pacific/Palau">
            <option value="Pacific/Pitcairn">
            <option value="Pacific/Pohnpei">
            <option value="Pacific/Port_Moresby">
            <option value="Pacific/Rarotonga">
            <option value="Pacific/Saipan">
            <option value="Pacific/Tahiti">
            <option value="Pacific/Tarawa">
            <option value="Pacific/Tongatapu">
            <option value="Pacific/Wake">
            <option value="Pacific/Wallis">
            <option value="UTC">
          </datalist>
        </div>

        <!-- DNS (required) -->
        <div class="col-12">
          <label class="form-label fw-semibold">DNS</label>
          <div class="row g-2">
            <div class="col-md-4">
              <label class="form-label fw-semibold">Domain</label>
              <input type="text" id="initDnsDomain" class="form-control" placeholder="example.com">
            </div>
            <div class="col-md-8">
              <label class="form-label fw-semibold">Nameservers <small class="text-muted fw-normal">— comma-separated</small></label>
              <input type="text" id="initDnsNs" class="form-control" placeholder="8.8.8.8, 8.8.4.4">
            </div>
          </div>
        </div>

        <!-- SMTP (required) -->
        <div class="col-12">
          <label class="form-label fw-semibold">SMTP</label>
          <div class="row g-2">
            <div class="col-md-4">
              <label class="form-label fw-semibold">Relay Host</label>
              <input type="text" id="initSmtpRelay" class="form-control" placeholder="smtp.example.com">
            </div>
            <div class="col-md-4">
              <label class="form-label fw-semibold">Sender Domain</label>
              <input type="text" id="initSmtpDomain" class="form-control" placeholder="example.com">
            </div>
            <div class="col-md-12 mt-2">
              <label class="form-label fw-semibold">Alert Email Addresses <small class="text-muted fw-normal">— optional, comma-separated</small></label>
              <input type="text" id="initAlertEmails" class="form-control" placeholder="admin@example.com, ops@example.com">
            </div>
          </div>
        </div>

        <!-- EULA -->
        <div class="col-12">
          <hr class="my-1">
          <label class="form-label fw-semibold">EULA Acceptance</label>
          <div class="form-check mb-2">
            <input class="form-check-input" type="checkbox" id="initEulaAccepted">
            <label class="form-check-label" for="initEulaAccepted">
              I agree to the Pure Storage End User License Agreement (EULA)
            </label>
          </div>
          <div class="row g-2">
            <div class="col-md-4"><input type="text" id="initEulaName"  class="form-control" placeholder="Full Name"></div>
            <div class="col-md-4"><input type="text" id="initEulaTitle" class="form-control" placeholder="Job Title"></div>
            <div class="col-md-4"><input type="text" id="initEulaOrg"   class="form-control" placeholder="Organization"></div>
          </div>
        </div>

        <!-- Skip connectivity tests -->
        <div class="col-12">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="initSkipConnTests">
            <label class="form-check-label" for="initSkipConnTests">
              Skip Connectivity Tests
              <small class="text-muted ms-1">— use for isolated environments with no internet connectivity</small>
            </label>
          </div>
        </div>

        <div class="col-12 d-flex gap-2 flex-wrap">
          <button class="btn btn-info fw-semibold text-white" onclick="runZtpInitialize(this)">
            <i class="bi bi-hdd-rack me-1"></i> Send Initialize Config
          </button>
          <button class="btn btn-outline-info fw-semibold" onclick="previewInitPayload(this)">
            <i class="bi bi-eye me-1"></i> Preview JSON
          </button>
          <button class="btn btn-outline-secondary fw-semibold" onclick="downloadInitPayload(this)">
            <i class="bi bi-download me-1"></i> Download JSON
          </button>
        </div>
        <div id="initValidationMsg" class="col-12 d-none">
          <div class="alert alert-danger py-2 mb-0"></div>
        </div>
      </div>

      <!-- Payload preview -->
      <div id="initPayloadPreview" class="mt-3 d-none">
        <hr>
        <div class="d-flex align-items-center justify-content-between mb-2">
          <span class="fw-semibold">Payload Preview</span>
          <button class="btn btn-sm btn-outline-secondary" onclick="downloadInitPayload(this)">
            <i class="bi bi-download me-1"></i> Download JSON
          </button>
        </div>
        <pre id="initPayloadBody" class="bg-dark text-light rounded p-3"
             style="max-height:400px;overflow:auto;font-size:0.85rem;white-space:pre-wrap"></pre>
      </div>

      <!-- Init response -->
      <div id="initResponse" class="mt-3 d-none">
        <hr>
        <div class="d-flex align-items-center gap-2 mb-2">
          <span class="fw-semibold">Initialize Response</span>
          <span id="initStatusBadge" class="badge fs-6"></span>
        </div>
        <pre id="initResponseBody" class="bg-dark text-light rounded p-3"
             style="max-height:300px;overflow:auto;font-size:0.85rem;white-space:pre-wrap"></pre>
      </div>
    </div>
  </div>
</div>


<!-- ZTE FlashArray Erasure -->
<div class="card mb-3 border-danger">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#zteCollapse">
    <span class="fw-semibold text-danger">
      <i class="bi bi-fire me-1"></i> ZTE FlashArray Erasure
    </span>
    <i class="bi bi-chevron-down"></i>
  </div>
  <div class="collapse" id="zteCollapse">
    <div class="card-body">

      <div class="alert alert-danger d-flex align-items-start gap-2 mb-3">
        <i class="bi bi-exclamation-triangle-fill fs-5 flex-shrink-0 mt-1"></i>
        <div>
          <strong>Destructive operation &#8212; ZTE permanently erases all data and configuration.</strong>
          Complete every item in the pre-erasure checklist below before starting. This cannot be undone.
        </div>
      </div>

      <!-- Pre-erasure checklist -->
      <div class="card border-warning mb-3">
        <div class="card-header bg-warning bg-opacity-10 d-flex justify-content-between align-items-center"
             style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#zteChecklist">
          <span class="fw-semibold text-warning-emphasis">
            <i class="bi bi-clipboard2-check me-1"></i> Pre-Erasure Checklist &#8212; complete all items before starting ZTE
          </span>
          <i class="bi bi-chevron-down"></i>
        </div>
        <div class="collapse show" id="zteChecklist">
          <div class="card-body pt-2 pb-2">
            <p class="text-muted mb-2" style="font-size:0.875rem">
              The ZTE start request will fail immediately if any of these conditions are not met.
              Use the Purity UI or REST API to complete each step, then eradicate before proceeding.
            </p>
            <div class="row g-0">
              <div class="col-md-6">
                <ul class="list-unstyled mb-0" style="font-size:0.9rem">
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Disable SafeMode</strong> &#8212; SafeMode must be turned off before ZTE can proceed</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Disconnect all hosts</strong> &#8212; remove host connections and host entries</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Delete &amp; eradicate all volumes</strong> &#8212; including all volume snapshots (exclude system volumes)</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Delete &amp; eradicate all protection groups (pgroups)</strong> &#8212; including pgroup snapshots</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Delete &amp; eradicate all pods</strong></li>
                </ul>
              </div>
              <div class="col-md-6">
                <ul class="list-unstyled mb-0" style="font-size:0.9rem">
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Remove all array connections</strong> &#8212; disconnect replication and pod stretch targets</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Remove offload targets</strong> &#8212; NFS, S3, and Azure offload configurations</li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Delete file systems, shares, and directory services</strong></li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Remove Active Directory configuration</strong></li>
                  <li class="mb-1"><i class="bi bi-square text-secondary me-2"></i><strong>Confirm authorization and business approval</strong> &#8212; data-retention, legal-hold, and change-management requirements satisfied</li>
                </ul>
              </div>
            </div>
            <div class="alert alert-warning py-2 px-3 mt-2 mb-0" style="font-size:0.875rem">
              <i class="bi bi-exclamation-circle me-1"></i>
              <strong>Eradication is required</strong> &#8212; deleted items enter a pending-eradication state.
              You must explicitly eradicate volumes, snapshots, pgroups, and pods (not just delete them)
              before ZTE will proceed.
            </div>
          </div>
        </div>
      </div>

      <div class="row g-3">

        <!-- Connection -->
        <div class="col-md-4">
          <label class="form-label fw-semibold">Array Management VIP / Hostname</label>
          <input type="text" id="zteVip" class="form-control" placeholder="192.168.1.100 or array.example.com">
        </div>
        <div class="col-md-2">
          <label class="form-label fw-semibold">API Version</label>
          <input type="text" id="zteApiVersion" class="form-control" value="2.56">
        </div>
        <div class="col-md-4">
          <label class="form-label fw-semibold">API Token</label>
          <input type="password" id="zteApiToken" class="form-control"
                 placeholder="API token for authentication" autocomplete="off">
        </div>
        <div class="col-md-2 d-flex align-items-end">
          <button class="btn btn-outline-secondary fw-semibold w-100" onclick="zteAuthenticate(this)">
            <i class="bi bi-key me-1"></i> Authenticate
          </button>
        </div>

        <div class="col-12 d-none" id="zteSessionRow">
          <label class="form-label fw-semibold">
            Session Token
            <small class="text-muted fw-normal">(x-auth-token &#8212; re-authenticate if requests return 401)</small>
          </label>
          <div class="input-group">
            <input type="text" id="zteSessionToken" class="form-control font-monospace" readonly>
            <button class="btn btn-outline-secondary" type="button"
                    onclick="navigator.clipboard.writeText(document.getElementById('zteSessionToken').value)">
              <i class="bi bi-clipboard"></i>
            </button>
          </div>
        </div>

        <!-- Phase 1 -->
        <div class="col-12"><hr class="my-1">
          <span class="fw-semibold">Phase 1 &mdash; Start Secure Wipe</span>
        </div>

        <div class="col-12">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" id="zteSkipPhonehome">
            <label class="form-check-label" for="zteSkipPhonehome">
              Dark-site array &#8212; skip phone-home check
              <small class="text-muted ms-1">
                Only use for arrays that intentionally cannot reach Pure Storage.
                Do not use to bypass unexpected connectivity issues.
              </small>
            </label>
          </div>
        </div>

        <div class="col-12 d-flex gap-2 flex-wrap">
          <button class="btn btn-danger fw-semibold" onclick="zteStartWipe(this)">
            <i class="bi bi-fire me-1"></i> Start ZTE Wipe
          </button>
          <button id="zteStatusBtn" class="btn btn-outline-secondary fw-semibold" onclick="zteCheckStatus(this)">
            <i class="bi bi-arrow-clockwise me-1"></i> Check Wipe Status
          </button>
          <button class="btn btn-outline-danger fw-semibold" onclick="zteCancelErasure(this)">
            <i class="bi bi-x-circle me-1"></i> Cancel ZTE
          </button>
        </div>

        <div id="zteStatusPanel" class="col-12 d-none">
          <div class="border rounded p-3 bg-light">
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="fw-semibold">Erasure Status</span>
              <span id="ztePhaseBadge" class="badge fs-6"></span>
            </div>
            <p id="ztePhaseDesc" class="text-muted mb-2" style="font-size:0.9rem"></p>
            <div id="zteRawResponse">
              <div class="d-flex align-items-center gap-2 mb-1">
                <small class="fw-semibold">Raw Response</small>
                <button id="zteCopyCertBtn" class="btn btn-sm btn-outline-secondary d-none"
                        onclick="zteCopyCert(this)">
                  <i class="bi bi-clipboard me-1"></i> Copy Certificate
                </button>
                <button id="zteDownloadCertBtn" class="btn btn-sm btn-outline-primary d-none"
                        onclick="zteDownloadCert()">
                  <i class="bi bi-download me-1"></i> Download Certificate
                </button>
              </div>
              <pre id="zteResponsePre" class="bg-dark text-light rounded p-2 mb-0"
                   style="max-height:250px;overflow:auto;font-size:0.8rem;white-space:pre-wrap"></pre>
            </div>
          </div>
        </div>

        <!-- Phase 2 -->
        <div class="col-12"><hr class="my-1">
          <span class="fw-semibold">Phase 2 &mdash; Finalize &amp; Reinstall Image</span>
          <p class="text-muted mt-1 mb-0" style="font-size:0.875rem">
            Only proceed after Phase 1 status shows <code>waiting_for_finalize</code>
            and the sanitization certificate has been saved.
          </p>
        </div>

        <div class="col-12">
          <div class="form-check form-check-inline">
            <input class="form-check-input" type="radio" name="zteImageMode"
                   id="zteImageAuto" value="auto" checked onchange="zteToggleImageSource()">
            <label class="form-check-label" for="zteImageAuto">
              Phoning-home (<code>image_source: auto</code>)
            </label>
          </div>
          <div class="form-check form-check-inline">
            <input class="form-check-input" type="radio" name="zteImageMode"
                   id="zteImageCustom" value="custom" onchange="zteToggleImageSource()">
            <label class="form-check-label" for="zteImageCustom">Dark-site (custom image source)</label>
          </div>
          <div id="zteImageSourceRow" class="mt-2 d-none">
            <input type="text" id="zteImageSource" class="form-control"
                   placeholder="http://fileserver:8080/download/purity.sh  or  file:///path/to/purity_iso.sh">
            <small class="text-muted">URL or local file URI (<code>file:///</code>) reachable by the array</small>
          </div>
        </div>

        <div class="col-12 d-flex gap-2 flex-wrap">
          <button class="btn btn-danger fw-semibold" onclick="zteFinalize(this)">
            <i class="bi bi-check2-circle me-1"></i> Finalize &amp; Reinstall Image
          </button>
        </div>

        <div id="zteActionResponse" class="col-12 d-none">
          <div class="border rounded p-3">
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="fw-semibold" id="zteActionLabel">Response</span>
              <span id="zteActionBadge" class="badge fs-6"></span>
            </div>
            <pre id="zteActionBody" class="bg-dark text-light rounded p-2 mb-0"
                 style="max-height:200px;overflow:auto;font-size:0.8rem;white-space:pre-wrap"></pre>
          </div>
        </div>

        <div id="zteError" class="col-12 d-none">
          <div class="alert alert-danger py-2 mb-0"></div>
        </div>

      </div>
    </div>
  </div>
</div>


</div><!-- /container -->

<!-- Move Modal -->
<div class="modal fade" id="moveModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-folder-symlink me-2"></i>Move File</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form method="POST" id="moveForm">
        <div class="modal-body">
          <p class="mb-3">Moving: <strong id="moveFileName"></strong></p>
          <label class="form-label fw-semibold">Destination folder</label>
          <select name="dest" class="form-select" required>
            <option value="">/ (root)</option>
            {% for d in all_dirs %}
            <option value="{{ d.value }}">{{ d.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
          <button type="submit" class="btn btn-primary"><i class="bi bi-folder-symlink me-1"></i>Move</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script src="/logos/bootstrap.bundle.min.js"></script>
<script>
function openMoveModal(relPath, name) {
  document.getElementById('moveFileName').textContent = name;
  document.getElementById('moveForm').action = '/move/' + relPath;
  new bootstrap.Modal(document.getElementById('moveModal')).show();
}

const ZTP_PHASES = [
  { key: 'install-not-started',      label: 'Not Started',         desc: 'ZTP pureinstall has not been started on this FlashArray.' },
  { key: 'install-in-progress',      label: 'Install In Progress', desc: 'The PATCH request has been received and pureinstall has begun.' },
  { key: 'download-in-progress',     label: 'Downloading',         desc: 'The .ppkg and .ppkg.sig files are being downloaded on CT1.' },
  { key: 'ct0-install-in-progress',  label: 'CT0 Installing',      desc: 'CT0 is fetching the downloaded files from CT1 and starting pureinstall.' },
  { key: 'ct1-install-in-progress',  label: 'CT1 Installing',      desc: 'CT0 pureinstall complete and rebooted. CT1 pureinstall now in progress.' },
  { key: 'install-complete',         label: 'Complete',            desc: 'Both controllers have rebooted. Purity should be up and running.' },
];

let _ztpPoller = null;

function _stopZtpPoller() {
  if (_ztpPoller !== null) { clearInterval(_ztpPoller); _ztpPoller = null; }
  const btn = document.getElementById('ztpStatusBtn');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Check Status';
    btn.className = 'btn btn-outline-secondary fw-semibold';
  }
}

function _applyZtpStatusData(data) {
  document.getElementById('ztpStatusPanel').classList.remove('d-none');
  const status = data.status || '';
  const phaseIdx = ZTP_PHASES.findIndex(p => p.key === status);
  const phase = ZTP_PHASES[phaseIdx] || { label: status || 'Unknown', desc: data.error || '' };
  const isComplete = status === 'install-complete';
  const isError = !data.status;

  const badge = document.getElementById('ztpPhaseBadge');
  badge.textContent = phase.label;
  badge.className = 'badge fs-6 ' + (isError ? 'bg-danger' : isComplete ? 'bg-success' : status === 'install-not-started' ? 'bg-secondary' : 'bg-primary');
  document.getElementById('ztpPhaseDesc').textContent = phase.desc;

  document.getElementById('ztpSteps').innerHTML = ZTP_PHASES.map((p, i) => {
    const done = phaseIdx >= 0 && i < phaseIdx;
    const active = i === phaseIdx;
    const cls = done ? 'bg-success text-white' : active ? 'bg-primary text-white' : 'bg-light text-muted border';
    return `<span class="badge rounded-pill px-3 py-2 ${cls}" style="font-size:0.8rem">${done ? '\\u2713 ' : ''}${p.label}</span>`;
  }).join('');

  const errBlock = document.getElementById('ztpErrorsBlock');
  const errors = data.errors;
  if (errors && errors.length) {
    errBlock.classList.remove('d-none');
    document.getElementById('ztpErrorsBody').textContent = JSON.stringify(errors, null, 2);
  } else {
    errBlock.classList.add('d-none');
  }
  document.getElementById('ztpCompleteNote').classList.toggle('d-none', !isComplete);
  return { isComplete, isError };
}

async function runZtpStatus(btn) {
  const ip = document.getElementById('ztpIp').value.trim();
  if (!ip) { alert('Enter the Controller 1 ZTP IP first.'); return; }

  // Second click while polling → stop
  if (_ztpPoller !== null) { _stopZtpPoller(); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Checking…';

  try {
    const resp = await fetch('/ztp-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip })
    });
    const data = await resp.json();
    const { isComplete, isError } = _applyZtpStatusData(data);

    if (!isComplete && !isError) {
      // Start 15-second auto-refresh
      _ztpPoller = setInterval(async () => {
        try {
          const r = await fetch('/ztp-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ip })
          });
          const { isComplete: done, isError: err } = _applyZtpStatusData(await r.json());
          if (done || err) _stopZtpPoller();
        } catch(e) { _stopZtpPoller(); }
      }, 15000);
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-stop-circle me-1"></i> Stop Auto-Refresh';
      btn.className = 'btn btn-outline-danger fw-semibold';
    }
  } finally {
    if (_ztpPoller === null) {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Check Status';
      btn.className = 'btn btn-outline-secondary fw-semibold';
    }
  }
}

async function runZtpInstall(btn) {
  const ip  = document.getElementById('ztpIp').value.trim();
  const pkg = document.getElementById('ztpPkg').value.trim();
  const sig = document.getElementById('ztpSig').value.trim();
  if (!ip || !pkg || !sig) { alert('Array IP, package path, and signature path are all required.'); return; }

  const payload = { package_path: pkg, sig_file_path: sig };

  if (document.getElementById('ztpDnsEnabled').checked) {
    const ns     = document.getElementById('ztpNs').value.trim();
    const search = document.getElementById('ztpSearch').value.trim();
    const domain = document.getElementById('ztpDomain').value.trim();
    payload.dns_servers = {};
    if (ns)     payload.dns_servers.nameservers = ns.split(',').map(s => s.trim()).filter(Boolean);
    if (search) payload.dns_servers.search = [search];
    if (domain) payload.dns_servers.domain = domain;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting…';

  try {
    const resp = await fetch('/ztp-install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, payload })
    });
    const data = await resp.json();

    document.getElementById('ztpResponse').classList.remove('d-none');
    const badge = document.getElementById('ztpStatusBadge');
    const s = data.status;
    badge.textContent = s ? `HTTP ${s}` : 'Error';
    badge.className = 'badge fs-6 ' + (!s ? 'bg-danger' : s < 300 ? 'bg-success' : s < 500 ? 'bg-warning text-dark' : 'bg-danger');
    let bodyText = data.body || data.error || '(empty response)';
    try { bodyText = JSON.stringify(JSON.parse(bodyText), null, 2); } catch(e) {}
    document.getElementById('ztpResponseBody').textContent = bodyText;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-lightning-charge-fill me-1"></i> Start PureInstall';
  }
}

function updateInitLabels() {
  const n = document.querySelector('input[name="initIfaceMode"]:checked').value;
  document.getElementById('initCt0Label').textContent = `ct0.eth${n}`;
  document.getElementById('initCt1Label').textContent = `ct1.eth${n}`;
  document.getElementById('initVirLabel').textContent = `vir${n}`;
}

function importInitPayload(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {
    let p;
    try { p = JSON.parse(e.target.result); }
    catch { alert('Invalid JSON file.'); return; }

    // Detect interface mode (eth0 vs eth4) from payload keys
    const n = (p['ct0.eth4'] || p['ct1.eth4'] || p['vir4']) ? '4' : '0';
    document.getElementById(n === '4' ? 'initModeEth4' : 'initModeEth0').checked = true;
    updateInitLabels();

    if (p.array_name !== undefined) document.getElementById('initArrayName').value = p.array_name;

    const ct0 = p[`ct0.eth${n}`] || {};
    if (ct0.address !== undefined) document.getElementById('initCt0Addr').value = ct0.address;
    if (ct0.netmask !== undefined) document.getElementById('initCt0Mask').value = ct0.netmask;
    if (ct0.gateway !== undefined) document.getElementById('initCt0Gw').value   = ct0.gateway;

    const ct1 = p[`ct1.eth${n}`] || {};
    if (ct1.address !== undefined) document.getElementById('initCt1Addr').value = ct1.address;
    if (ct1.netmask !== undefined) document.getElementById('initCt1Mask').value = ct1.netmask;
    if (ct1.gateway !== undefined) document.getElementById('initCt1Gw').value   = ct1.gateway;

    const vir = p[`vir${n}`] || {};
    if (vir.address !== undefined) document.getElementById('initVirAddr').value = vir.address;
    if (vir.netmask !== undefined) document.getElementById('initVirMask').value = vir.netmask;
    if (vir.gateway !== undefined) document.getElementById('initVirGw').value   = vir.gateway;

    if (p.ntp_servers) document.getElementById('initNtp').value = p.ntp_servers.join(', ');
    if (p.timezone)    document.getElementById('initTz').value  = p.timezone;

    const dns = p.dns || {};
    if (dns.domain)      document.getElementById('initDnsDomain').value = dns.domain;
    if (dns.nameservers) document.getElementById('initDnsNs').value     = dns.nameservers.join(', ');

    const smtp = p.smtp || {};
    if (smtp.relay_host)    document.getElementById('initSmtpRelay').value  = smtp.relay_host;
    if (smtp.sender_domain) document.getElementById('initSmtpDomain').value = smtp.sender_domain;

    if (p.alert_emails) document.getElementById('initAlertEmails').value = p.alert_emails.join(', ');

    const eula = (p.eula_acceptance || {});
    const by   = eula.accepted_by || {};
    if (eula.accepted)       document.getElementById('initEulaAccepted').checked = true;
    if (by.full_name)        document.getElementById('initEulaName').value  = by.full_name;
    if (by.job_title)        document.getElementById('initEulaTitle').value = by.job_title;
    if (by.organization)     document.getElementById('initEulaOrg').value   = by.organization;

    input.value = '';
  };
  reader.readAsText(file);
}

function _showInitError(msg) {
  const wrap = document.getElementById('initValidationMsg');
  if (!wrap) { alert(msg); return; }
  const alertEl = wrap.querySelector('.alert');
  if (alertEl) alertEl.textContent = msg;
  wrap.classList.remove('d-none');
  wrap.scrollIntoView({ block: 'nearest' });
}

function _clearInitError() {
  const el = document.getElementById('initValidationMsg');
  if (el) el.classList.add('d-none');
}

// Builds just the JSON payload. Does NOT require the ZTP IP (used by Preview/Download).
function buildPayloadOnly() {
  _clearInitError();
  const n         = document.querySelector('input[name="initIfaceMode"]:checked').value;
  const arrayName = document.getElementById('initArrayName').value.trim();
  const ct0addr   = document.getElementById('initCt0Addr').value.trim();
  const ct0mask   = document.getElementById('initCt0Mask').value.trim();
  const ct0gw     = document.getElementById('initCt0Gw').value.trim();
  const ct1addr   = document.getElementById('initCt1Addr').value.trim();
  const ct1mask   = document.getElementById('initCt1Mask').value.trim();
  const ct1gw     = document.getElementById('initCt1Gw').value.trim();
  const viraddr   = document.getElementById('initVirAddr').value.trim();
  const virmask   = document.getElementById('initVirMask').value.trim();
  const virgw     = document.getElementById('initVirGw').value.trim();
  const ntp       = document.getElementById('initNtp').value.trim();
  const tz        = document.getElementById('initTz').value.trim();
  const dnsDomain = document.getElementById('initDnsDomain').value.trim();
  const dnsNs     = document.getElementById('initDnsNs').value.trim();
  const smtpRelay = document.getElementById('initSmtpRelay').value.trim();
  const smtpSender= document.getElementById('initSmtpDomain').value.trim();

  if (!arrayName || !ct0addr || !ct0mask || !ct0gw ||
      !ct1addr || !ct1mask || !ct1gw || !viraddr || !virmask || !virgw || !ntp || !tz) {
    _showInitError('Array name, all IP/mask/gateway fields, NTP, and timezone are required.');
    return null;
  }
  if (!dnsDomain || !dnsNs) {
    _showInitError('DNS Domain and Nameservers are required.');
    return null;
  }
  if (!smtpRelay || !smtpSender) {
    _showInitError('SMTP Relay Host and Sender Domain are required.');
    return null;
  }
  if (!document.getElementById('initEulaAccepted').checked) {
    _showInitError('You must accept the EULA to proceed.');
    return null;
  }
  const eulaName  = document.getElementById('initEulaName').value.trim();
  const eulaTitle = document.getElementById('initEulaTitle').value.trim();
  const eulaOrg   = document.getElementById('initEulaOrg').value.trim();
  if (!eulaName || !eulaTitle || !eulaOrg) {
    _showInitError('EULA full name, job title, and organization are required.');
    return null;
  }

  const emails = document.getElementById('initAlertEmails').value.trim();

  const payload = {
    array_name: arrayName,
    [`ct0.eth${n}`]: { address: ct0addr, netmask: ct0mask, gateway: ct0gw },
    [`ct1.eth${n}`]: { address: ct1addr, netmask: ct1mask, gateway: ct1gw },
    [`vir${n}`]:     { address: viraddr, netmask: virmask, gateway: virgw },
    ntp_servers: ntp.split(',').map(s => s.trim()).filter(Boolean),
    timezone: tz,
    dns: {
      domain: dnsDomain,
      nameservers: dnsNs.split(',').map(s => s.trim()).filter(Boolean)
    },
    smtp: {
      relay_host: smtpRelay,
      sender_domain: smtpSender
    },
    eula_acceptance: {
      accepted: true,
      accepted_by: { full_name: eulaName, job_title: eulaTitle, organization: eulaOrg }
    }
  };

  if (emails) payload.alert_emails = emails.split(',').map(s => s.trim()).filter(Boolean);
  if (document.getElementById('initSkipConnTests').checked) payload.skip_connectivity_tests = true;
  return payload;
}

// Builds payload + validates ZTP IP. Used by Send Initialize Config.
function buildInitPayload() {
  const ip = document.getElementById('initIp').value.trim();
  if (!ip) {
    _showInitError('Controller 1 ZTP IP is required to send the initialize config.');
    return null;
  }
  const payload = buildPayloadOnly();
  if (!payload) return null;
  return { ip, payload };
}

function previewInitPayload(btn) {
  const orig = btn ? btn.innerHTML : '';
  if (btn) btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Building...';
  try {
    const payload = buildPayloadOnly();
    if (!payload) {
      if (btn) btn.innerHTML = orig;
      return;
    }
    const bodyEl = document.getElementById('initPayloadBody');
    const preview = document.getElementById('initPayloadPreview');
    if (!bodyEl || !preview) { alert('Preview elements not found — please reload the page.'); if (btn) btn.innerHTML = orig; return; }
    bodyEl.textContent = JSON.stringify(payload, null, 2);
    preview.style.display = 'block';
    preview.classList.remove('d-none');
    preview.scrollIntoView({ block: 'nearest' });
    if (btn) { btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Preview shown below'; setTimeout(() => { btn.innerHTML = orig; }, 3000); }
  } catch(e) {
    alert('Preview error: ' + e.message);
    if (btn) btn.innerHTML = orig;
  }
}

function downloadInitPayload(btn) {
  const orig = btn ? btn.innerHTML : '';
  if (btn) btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Preparing...';
  try {
    const payload = buildPayloadOnly();
    if (!payload) {
      if (btn) btn.innerHTML = orig;
      return;
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = (payload.array_name || 'flasharray') + '-initialize-config.json';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    if (btn) { btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Downloaded'; setTimeout(() => { btn.innerHTML = orig; }, 3000); }
  } catch(e) {
    alert('Download error: ' + e.message);
    if (btn) btn.innerHTML = orig;
  }
}

async function runZtpInitialize(btn) {
  const result = buildInitPayload();
  if (!result) return;
  const { ip, payload } = result;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Initializing…';

  try {
    const resp = await fetch('/ztp-initialize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, payload })
    });
    const data = await resp.json();

    document.getElementById('initResponse').classList.remove('d-none');
    const badge = document.getElementById('initStatusBadge');
    const s = data.status;
    badge.textContent = s ? `HTTP ${s}` : 'Error';
    badge.className = 'badge fs-6 ' + (!s ? 'bg-danger' : s < 300 ? 'bg-success' : s < 500 ? 'bg-warning text-dark' : 'bg-danger');
    let bodyText = data.body || data.error || '(empty response)';
    try { bodyText = JSON.stringify(JSON.parse(bodyText), null, 2); } catch(e) {}
    document.getElementById('initResponseBody').textContent = bodyText;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-hdd-rack me-1"></i> Send Initialize Config';
  }
}

function saveCopyLinkIp(val) {
  if (val.trim()) localStorage.setItem('copyLinkIpOverride', val.trim());
  else localStorage.removeItem('copyLinkIpOverride');
}

function clearCopyLinkIp() {
  localStorage.removeItem('copyLinkIpOverride');
  const el = document.getElementById('copyLinkIpOverride');
  if (el) el.value = '';
}

function _copyLinkBase() {
  const override = (localStorage.getItem('copyLinkIpOverride') || '').trim();
  if (override) {
    const port = window.location.port ? ':' + window.location.port : '';
    return window.location.protocol + '//' + override + port;
  }
  return window.location.origin;
}

document.addEventListener('DOMContentLoaded', () => {
  const saved = localStorage.getItem('copyLinkIpOverride');
  const el = document.getElementById('copyLinkIpOverride');
  if (saved && el) el.value = saved;
});

function copyLink(btn, relPath) {
  const url = _copyLinkBase() + '/download/' + relPath;
  const confirm = () => {
    const orig = btn.innerHTML;
    btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
    btn.classList.replace('btn-outline-secondary', 'btn-success');
    setTimeout(() => {
      btn.innerHTML = orig;
      btn.classList.replace('btn-success', 'btn-outline-secondary');
    }, 2000);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(confirm);
  } else {
    const ta = document.createElement('textarea');
    ta.value = url;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    confirm();
  }
}

// ── DHCP Server ──────────────────────────────────────────────────────────────

async function loadDhcpStatus() {
  const badge = document.getElementById('dhcpStatusBadge');
  const headerBadge = document.getElementById('dhcpHeaderBadge');
  let data;
  try {
    const resp = await fetch('/dhcp-status');
    data = await resp.json();
  } catch (err) {
    badge.textContent = 'Error';
    badge.className = 'badge fs-6 bg-danger';
    if (headerBadge) headerBadge.innerHTML = '<span class="badge bg-danger ms-2">Error</span>';
    console.error('loadDhcpStatus failed:', err);
    return;
  }
  const stopBtn    = document.getElementById('dhcpStopBtn');
  const startBtn   = document.getElementById('dhcpStartBtn');
  const restartBtn = document.getElementById('dhcpRestartBtn');

  if (data.running) {
    badge.textContent = 'Running';
    badge.className = 'badge fs-6 bg-success';
    headerBadge.innerHTML = '<span class="badge bg-success ms-2">Running</span>';
    stopBtn.style.display = '';
    startBtn.style.display = 'none';
    restartBtn.style.display = '';
    if (data.config) {
      document.getElementById('dhcpIface').value      = data.config.interface   || '';
      document.getElementById('dhcpSubnet').value     = data.config.subnet      || '';
      document.getElementById('dhcpRangeStart').value = data.config.range_start || '';
      document.getElementById('dhcpRangeEnd').value   = data.config.range_end   || '';
      document.getElementById('dhcpServerIp').value   = data.config.server_ip   || '';
      updateIfaceIpDisplay();
    }
  } else {
    badge.textContent = 'Stopped';
    badge.className = 'badge fs-6 bg-secondary';
    headerBadge.innerHTML = '<span class="badge bg-secondary ms-2">Stopped</span>';
    stopBtn.style.display = 'none';
    startBtn.style.display = '';
    restartBtn.style.display = 'none';
    if (data.config) {
      document.getElementById('dhcpIface').value      = data.config.interface   || '';
      document.getElementById('dhcpSubnet').value     = data.config.subnet      || '';
      document.getElementById('dhcpRangeStart').value = data.config.range_start || '';
      document.getElementById('dhcpRangeEnd').value   = data.config.range_end   || '';
      document.getElementById('dhcpServerIp').value   = data.config.server_ip   || '';
      updateIfaceIpDisplay();
    }
  }
}

let _dhcpIfaceMap = {};

async function loadDhcpInterfaces() {
  const sel = document.getElementById('dhcpIface');
  const currentVal = sel.value;
  _dhcpIfaceMap = {};
  let data;
  try {
    const resp = await fetch('/dhcp-interfaces');
    data = await resp.json();
  } catch (err) {
    sel.innerHTML = '<option value="">(error loading interfaces)</option>';
    console.error('loadDhcpInterfaces failed:', err);
    return;
  }
  if (data.error && (!data.interfaces || !data.interfaces.length)) {
    sel.innerHTML = '<option value="">(error: ' + data.error + ')</option>';
    return;
  }
  sel.innerHTML = '<option value="">Select interface...</option>';
  (data.interfaces || []).forEach(iface => {
    _dhcpIfaceMap[iface.name] = iface.addresses || [];
    const opt = document.createElement('option');
    opt.value = iface.name;
    const addrs = iface.addresses && iface.addresses.length ? ' - ' + iface.addresses.join(', ') : '';
    opt.textContent = iface.name + addrs;
    sel.appendChild(opt);
  });
  if (currentVal) sel.value = currentVal;
  updateIfaceIpDisplay();
}

function updateIfaceIpDisplay() {
  const sel = document.getElementById('dhcpIface');
  const display = document.getElementById('dhcpIfaceIpDisplay');
  const iface = sel.value;
  const addrs = _dhcpIfaceMap[iface];
  if (iface && addrs && addrs.length) {
    display.innerHTML = '<i class="bi bi-ethernet me-1 text-info"></i><strong>Current IP:</strong> ' +
      addrs.map(a => '<code>' + a + '</code>').join(', ');
  } else if (iface) {
    display.innerHTML = '<span class="text-muted fst-italic">No IP address assigned</span>';
  } else {
    display.innerHTML = '';
  }
}

async function dhcpStart(btn) {
  const iface    = document.getElementById('dhcpIface').value.trim();
  const subnet   = document.getElementById('dhcpSubnet').value.trim();
  const start    = document.getElementById('dhcpRangeStart').value.trim();
  const end      = document.getElementById('dhcpRangeEnd').value.trim();
  const serverIp = document.getElementById('dhcpServerIp').value.trim();
  if (!iface || !subnet || !start || !end || !serverIp) {
    alert('Interface, subnet, range start, range end, and server IP address are all required.'); return;
  }
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting…';
  try {
    const resp = await fetch('/dhcp-start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interface: iface, subnet, range_start: start, range_end: end, server_ip: serverIp })
    });
    const data = await resp.json();
    if (data.error) { alert('Error: ' + data.error); }
    await loadDhcpStatus();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-play-fill me-1"></i> Enable DHCP Server';
  }
}

async function dhcpStop(btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Stopping…';
  try {
    const resp = await fetch('/dhcp-stop', { method: 'POST' });
    const data = await resp.json();
    if (data.error) { alert('Error: ' + data.error); }
    await loadDhcpStatus();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-stop-fill me-1"></i> Disable DHCP Server';
  }
}

async function dhcpRestart(btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Restarting…';
  try {
    const resp = await fetch('/dhcp-restart', { method: 'POST' });
    const data = await resp.json();
    if (data.error) { alert('Error: ' + data.error); }
    await loadDhcpStatus();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i> Restart DHCP';
  }
}

async function loadDhcpLeases(btn) {
  const panel = document.getElementById('dhcpLeasesPanel');
  const tbody = document.getElementById('dhcpLeasesBody');
  panel.classList.remove('d-none');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading…';
  try {
    const resp = await fetch('/dhcp-leases');
    const data = await resp.json();
    const leases = data.leases || [];
    if (!leases.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-muted fst-italic text-center">No active leases.</td></tr>';
    } else {
      tbody.innerHTML = leases.map(l => `
        <tr>
          <td><code>${l.ip}</code></td>
          <td><code>${l.mac}</code></td>
          <td>${l.hostname || '<span class="text-muted">—</span>'}</td>
          <td>${l.expiry}</td>
        </tr>`).join('');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-table me-1"></i> Show Active Leases';
  }
}

async function loadDhcpLogs(btn) {
  const panel = document.getElementById('dhcpLogsPanel');
  const body  = document.getElementById('dhcpLogsBody');
  panel.classList.remove('d-none');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';
  try {
    const resp = await fetch('/dhcp-logs');
    const data = await resp.json();
    if (data.error) {
      body.textContent = 'Error reading logs: ' + data.error;
    } else {
      body.textContent = (data.lines || []).join('\\n') || '(no log output yet — start the DHCP server first)';
    }
  } catch (err) {
    body.textContent = 'Failed to fetch logs: ' + err;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-terminal me-1"></i> Show Logs';
  }
}

// Init DHCP section: Bootstrap collapse event (primary) + page load fallback
document.getElementById('dhcpCollapse').addEventListener('show.bs.collapse', () => {
  loadDhcpInterfaces();
  loadDhcpStatus();
});

// Fallback: also load on page ready in case Bootstrap JS isn't available
// or the section is already expanded. Safe to call even when section is hidden.
document.addEventListener('DOMContentLoaded', () => {
  loadDhcpInterfaces();
  loadDhcpStatus();
});
// ── ZTE FlashArray Erasure ────────────────────────────────────────────────────
let _ztePoller = null;
let _zteLastResponse = null;

const ZTE_STATUSES = {
  'resetting':            { label: 'Wiping',            cls: 'bg-warning text-dark', desc: 'Drive wipe in progress (~30 min). REST API may be temporarily unavailable.' },
  'waiting_for_finalize': { label: 'Ready to Finalize', cls: 'bg-info text-white',   desc: 'Phase 1 complete. Save the sanitization certificate, then run Finalize & Reinstall.' },
  'reset_failed':         { label: 'Wipe Failed',       cls: 'bg-danger',            desc: 'Check failure details and correct pre-erasure conditions before retrying.' },
  'download_failed':      { label: 'Download Failed',   cls: 'bg-danger',            desc: 'Image download failed. Check network and image source reachability.' },
  'reimage_failed':       { label: 'Reimage Failed',    cls: 'bg-danger',            desc: 'Image reinstall failed. Check image source and retry finalization.' },
};

function _zteInputs() {
  return {
    vip:           (document.getElementById('zteVip').value || '').trim(),
    api_version:   (document.getElementById('zteApiVersion').value || '2.56').trim(),
    session_token: (document.getElementById('zteSessionToken').value || '').trim(),
  };
}

function _showZteError(msg) {
  const el = document.getElementById('zteError');
  if (!el) return;
  el.classList.remove('d-none');
  el.querySelector('.alert').textContent = msg;
}

function _clearZteError() {
  const el = document.getElementById('zteError');
  if (el) el.classList.add('d-none');
}

function _stopZtePoller() {
  if (_ztePoller !== null) { clearInterval(_ztePoller); _ztePoller = null; }
  const btn = document.getElementById('zteStatusBtn');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Check Wipe Status';
    btn.className = 'btn btn-outline-secondary fw-semibold';
  }
}

function _applyZteStatusData(data) {
  _clearZteError();
  const items = data.items || (Array.isArray(data) ? data : [data]);
  const item  = items[0] || {};
  const status = item.status || data.status || '';
  const info   = ZTE_STATUSES[status] || { label: status || 'Unknown', cls: 'bg-secondary', desc: '' };
  const isDone = ['waiting_for_finalize','reset_failed','download_failed','reimage_failed'].includes(status);

  document.getElementById('zteStatusPanel').classList.remove('d-none');
  const badge = document.getElementById('ztePhaseBadge');
  badge.textContent = info.label;
  badge.className = 'badge fs-6 ' + info.cls;
  document.getElementById('ztePhaseDesc').textContent = info.desc;

  _zteLastResponse = data;
  document.getElementById('zteResponsePre').textContent = JSON.stringify(data, null, 2);

  const certPresent = !!(item.sanitization_certificate);
  document.getElementById('zteCopyCertBtn').classList.toggle('d-none', !certPresent);
  document.getElementById('zteDownloadCertBtn').classList.toggle('d-none', !certPresent);

  return { status, isDone };
}

function _showZteActionResponse(label, data) {
  const panel = document.getElementById('zteActionResponse');
  panel.classList.remove('d-none');
  document.getElementById('zteActionLabel').textContent = label + ' Response';
  const badge = document.getElementById('zteActionBadge');
  const s = data.status;
  if (s) {
    badge.textContent = 'HTTP ' + s;
    badge.className = 'badge fs-6 ' + (s < 300 ? 'bg-success' : s < 500 ? 'bg-warning text-dark' : 'bg-danger');
  } else if (data.error) {
    badge.textContent = 'Error';
    badge.className = 'badge fs-6 bg-danger';
  } else {
    badge.textContent = '';
    badge.className = 'badge fs-6';
  }
  let body = data.body || data.error || JSON.stringify(data, null, 2);
  try { body = JSON.stringify(JSON.parse(body), null, 2); } catch(e) {}
  document.getElementById('zteActionBody').textContent = body;
}

async function zteAuthenticate(btn) {
  _clearZteError();
  const vip   = (document.getElementById('zteVip').value || '').trim();
  const token = (document.getElementById('zteApiToken').value || '').trim();
  if (!vip || !token) { _showZteError('Array VIP and API token are required.'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Authenticating…';

  try {
    const resp = await fetch('/zte-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vip, api_token: token })
    });
    const data = await resp.json();
    if (data.error) { _showZteError('Authentication failed: ' + data.error); btn.disabled = false; btn.innerHTML = '<i class="bi bi-key me-1"></i> Authenticate'; return; }
    document.getElementById('zteSessionToken').value = data.session_token;
    document.getElementById('zteSessionRow').classList.remove('d-none');
    btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Authenticated';
    btn.className = 'btn btn-success fw-semibold w-100';
    setTimeout(() => {
      btn.innerHTML = '<i class="bi bi-key me-1"></i> Re-Authenticate';
      btn.className = 'btn btn-outline-secondary fw-semibold w-100';
      btn.disabled = false;
    }, 2000);
  } catch(e) {
    _showZteError('Request failed: ' + e.message);
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-key me-1"></i> Authenticate';
  }
}

async function zteStartWipe(btn) {
  _clearZteError();
  const { vip, api_version, session_token } = _zteInputs();
  if (!vip)          { _showZteError('Array VIP is required.'); return; }
  if (!session_token){ _showZteError('Authenticate first to get a session token.'); return; }

  const skip = document.getElementById('zteSkipPhonehome').checked;
  const mode = skip ? 'dark-site (skip_phonehome_check=true)' : 'phoning-home (skip_phonehome_check=false)';
  if (!confirm(
    'WARNING: This will permanently erase all data on ' + vip + '.\\n\\n' +
    'Mode: ' + mode + '\\n\\n' +
    'Confirm the pre-erasure checklist is complete and approvals are in place.\\n\\nClick OK to start.'
  )) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting…';
  try {
    const resp = await fetch('/zte-start-wipe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vip, api_version, session_token, skip_phonehome_check: skip })
    });
    const data = await resp.json();
    _showZteActionResponse('Start Wipe', data);
    if (data.error) _showZteError(data.error);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-fire me-1"></i> Start ZTE Wipe';
  }
}

async function zteCheckStatus(btn) {
  _clearZteError();
  const { vip, api_version, session_token } = _zteInputs();
  if (!vip)          { _showZteError('Array VIP is required.'); return; }
  if (!session_token){ _showZteError('Authenticate first to get a session token.'); return; }

  if (_ztePoller !== null) { _stopZtePoller(); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Checking…';

  try {
    const resp = await fetch('/zte-erasure-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vip, api_version, session_token })
    });
    const data = await resp.json();
    if (!data.ok) { _showZteError(data.error || 'Status check failed'); return; }
    const { isDone } = _applyZteStatusData(data.data);

    if (!isDone) {
      _ztePoller = setInterval(async () => {
        try {
          const r = await fetch('/zte-erasure-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vip, api_version, session_token })
          });
          const d = await r.json();
          if (!d.ok) { _stopZtePoller(); return; }
          const { isDone: done } = _applyZteStatusData(d.data);
          if (done) _stopZtePoller();
        } catch(e) { _stopZtePoller(); }
      }, 30000);
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-stop-circle me-1"></i> Stop Auto-Refresh';
      btn.className = 'btn btn-outline-danger fw-semibold';
    }
  } catch(e) {
    _showZteError('Request failed: ' + e.message);
  } finally {
    if (_ztePoller === null) {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Check Wipe Status';
      btn.className = 'btn btn-outline-secondary fw-semibold';
    }
  }
}

async function zteFinalize(btn) {
  _clearZteError();
  const { vip, api_version, session_token } = _zteInputs();
  if (!vip)          { _showZteError('Array VIP is required.'); return; }
  if (!session_token){ _showZteError('Authenticate first to get a session token.'); return; }

  const isCustom   = document.getElementById('zteImageCustom').checked;
  const imageSource = isCustom ? (document.getElementById('zteImageSource').value || '').trim() : 'auto';
  if (isCustom && !imageSource) { _showZteError('Image source URL or path is required for dark-site finalization.'); return; }

  if (!confirm(
    'WARNING: Finalizing will delete the sanitization certificate from the array and begin image reinstallation (~40 min).\\n\\n' +
    'Confirm the certificate has been saved before continuing.\\n\\nClick OK to finalize.'
  )) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Finalizing…';
  try {
    const resp = await fetch('/zte-finalize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vip, api_version, session_token, image_source: imageSource })
    });
    const data = await resp.json();
    _showZteActionResponse('Finalize', data);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-check2-circle me-1"></i> Finalize &amp; Reinstall Image';
  }
}

async function zteCancelErasure(btn) {
  _clearZteError();
  const { vip, api_version, session_token } = _zteInputs();
  if (!vip || !session_token) { _showZteError('Array VIP and session token are required.'); return; }
  if (!confirm('Cancel the current ZTE operation on ' + vip + '?\\n\\nThis sends DELETE /arrays/erasures.')) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Cancelling…';
  try {
    const resp = await fetch('/zte-cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vip, api_version, session_token })
    });
    const data = await resp.json();
    _showZteActionResponse('Cancel ZTE', data);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-x-circle me-1"></i> Cancel ZTE';
  }
}

function zteToggleImageSource() {
  const custom = document.getElementById('zteImageCustom').checked;
  document.getElementById('zteImageSourceRow').classList.toggle('d-none', !custom);
}

function zteCopyCert(btn) {
  const pre = document.getElementById('zteResponsePre').textContent;
  let cert = pre;
  try {
    const parsed = JSON.parse(pre);
    const items = parsed.items || (Array.isArray(parsed) ? parsed : [parsed]);
    const c = (items[0] || {}).sanitization_certificate;
    if (c) cert = c;
  } catch(e) {}
  navigator.clipboard.writeText(cert).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '<i class="bi bi-check2 me-1"></i> Copied!';
    setTimeout(() => { btn.innerHTML = orig; }, 2000);
  });
}

function zteDownloadCert() {
  const pre = document.getElementById('zteResponsePre').textContent;
  let cert = pre;
  let filename = 'sanitization-certificate.txt';
  try {
    const parsed = JSON.parse(pre);
    const items = parsed.items || (Array.isArray(parsed) ? parsed : [parsed]);
    const item = items[0] || {};
    if (item.sanitization_certificate) cert = item.sanitization_certificate;
    if (item.id) filename = item.id + '-sanitization-certificate.txt';
  } catch(e) {}
  const a = document.createElement('a');
  a.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(cert);
  a.download = filename;
  a.click();
}

</script>
</body>
</html>
"""


def safe_path(subpath: str) -> Path:
    """Resolve subpath under BASE_DIR, reject traversal attempts."""
    subpath = subpath.lstrip("/")
    resolved = (BASE_DIR / subpath).resolve()
    if not str(resolved).startswith(str(BASE_DIR.resolve())):
        abort(403)
    return resolved


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def list_all_dirs() -> list:
    dirs = []
    for item in sorted(BASE_DIR.rglob("*")):
        if item.is_dir():
            rel = str(item.relative_to(BASE_DIR))
            dirs.append({"label": rel, "value": rel})
    return dirs


def build_breadcrumbs(subpath: str):
    parts = [p for p in subpath.strip("/").split("/") if p]
    crumbs = []
    for i, name in enumerate(parts):
        crumbs.append({"name": name, "path": "/".join(parts[: i + 1])})
    return crumbs


LOGOS_DIR = Path(__file__).parent / "assets"

@app.route("/logos/<path:filename>")
def logos(filename):
    return send_from_directory(LOGOS_DIR, filename)


@app.route("/", defaults={"subpath": ""})
@app.route("/browse/<path:subpath>")
def index(subpath):
    directory = safe_path(subpath)
    if not directory.exists():
        abort(404)
    if not directory.is_dir():
        return redirect(url_for("download", subpath=subpath))

    entries = []
    for item in sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        rel = str(item.relative_to(BASE_DIR))
        entries.append({
            "name": item.name,
            "rel_path": rel,
            "is_dir": item.is_dir(),
            "size": human_size(item.stat().st_size) if item.is_file() else "",
        })

    parent_path = str(Path(subpath).parent) if subpath else ""
    if parent_path == ".":
        parent_path = ""

    return render_template_string(
        HTML,
        entries=entries,
        current_path=subpath,
        parent_path=parent_path,
        breadcrumbs=build_breadcrumbs(subpath),
        all_dirs=list_all_dirs(),
    )


@app.route("/download/<path:subpath>")
def download(subpath):
    target = safe_path(subpath)
    if not target.is_file():
        abort(404)
    return send_from_directory(target.parent, target.name, as_attachment=True)


@app.route("/upload/<path:subpath>", methods=["POST"], defaults={"subpath": ""})
@app.route("/upload/", methods=["POST"], defaults={"subpath": ""})
@app.route("/upload/<path:subpath>", methods=["POST"])
def upload(subpath):
    directory = safe_path(subpath)
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        flash("No files selected.", "error")
        return redirect(url_for("index", subpath=subpath))

    saved = 0
    for f in files:
        if f.filename:
            filename = secure_filename(f.filename)
            f.save(directory / filename)
            saved += 1

    flash(f"Uploaded {saved} file(s).", "success")
    return redirect(url_for("index", subpath=subpath))


@app.route("/mkdir/", methods=["POST"], defaults={"subpath": ""})
@app.route("/mkdir/<path:subpath>", methods=["POST"])
def mkdir(subpath):
    directory = safe_path(subpath)
    folder_name = secure_filename(request.form.get("folder_name", "").strip())
    if not folder_name:
        flash("Folder name cannot be empty.", "error")
        return redirect(url_for("index", subpath=subpath))

    new_dir = directory / folder_name
    if new_dir.exists():
        flash(f"'{folder_name}' already exists.", "error")
    else:
        new_dir.mkdir(parents=True)
        flash(f"Folder '{folder_name}' created.", "success")

    return redirect(url_for("index", subpath=subpath))


@app.route("/fetch/", methods=["POST"], defaults={"subpath": ""})
@app.route("/fetch/<path:subpath>", methods=["POST"])
def fetch_url(subpath):
    directory = safe_path(subpath)
    url = request.form.get("url", "").strip()

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        flash("Only http:// and https:// URLs are supported.", "error")
        return redirect(url_for("index", subpath=subpath))

    url_filename = parsed.path.rstrip("/").rsplit("/", 1)[-1] or "downloaded_file"
    filename = secure_filename(url_filename) or "downloaded_file"
    dest = directory / filename

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZTP-FileServer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(dest, "wb") as f:
                shutil.copyfileobj(response, f)
        flash(f"Fetched '{filename}' successfully.", "success")
    except Exception as e:
        flash(f"Failed to fetch URL: {e}", "error")
        if dest.exists():
            dest.unlink()

    return redirect(url_for("index", subpath=subpath))


@app.route("/move/<path:subpath>", methods=["POST"])
def move(subpath):
    source = safe_path(subpath)
    if not source.is_file():
        abort(404)

    dest_rel = request.form.get("dest", "").strip().lstrip("/")
    dest_dir = safe_path(dest_rel)
    if not dest_dir.is_dir():
        flash("Destination folder does not exist.", "error")
    elif (dest_dir / source.name).exists():
        flash(f"'{source.name}' already exists in the destination.", "error")
    else:
        shutil.move(str(source), str(dest_dir / source.name))
        flash(f"Moved '{source.name}' to /{dest_rel or 'root'}.", "success")

    parent = str(source.parent.relative_to(BASE_DIR))
    if parent == ".":
        parent = ""
    return redirect(url_for("index", subpath=parent))


@app.route("/delete/<path:subpath>", methods=["POST"])
def delete(subpath):
    target = safe_path(subpath)
    parent = str(target.parent.relative_to(BASE_DIR)) if target.parent != BASE_DIR else ""
    if parent == ".":
        parent = ""

    if not target.exists():
        abort(404)
    if target.is_dir():
        shutil.rmtree(target)
        flash(f"Folder '{target.name}' deleted.", "success")
    else:
        target.unlink()
        flash(f"File '{target.name}' deleted.", "success")

    return redirect(url_for("index", subpath=parent))


@app.route("/ztp-status", methods=["POST"])
def ztp_status():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "Controller 1 ZTP IP required"}), 400

    url = f"http://{ip}:8081/array-purity-installations"
    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return jsonify({"status": body.get("status"), "errors": body.get("errors", [])})
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"HTTP {e.code}", "errors": []})
    except Exception as e:
        return jsonify({"error": str(e), "errors": []})


@app.route("/ztp-install", methods=["POST"])
def ztp_install():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    payload = data.get("payload", {})

    if not ip:
        return jsonify({"error": "Controller 1 ZTP IP required"}), 400
    if not payload.get("package_path") or not payload.get("sig_file_path"):
        return jsonify({"error": "package_path and sig_file_path are required"}), 400

    url = f"http://{ip}:8081/array-purity-installations"
    body_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="PATCH"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return jsonify({"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")})
    except urllib.error.HTTPError as e:
        return jsonify({"status": e.code, "body": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/ztp-initialize", methods=["POST"])
def ztp_initialize():
    data = request.get_json(force=True)
    ip = data.get("ip", "").strip()
    payload = data.get("payload", {})

    if not ip:
        return jsonify({"error": "Controller 1 ZTP IP required"}), 400
    if not payload.get("array_name"):
        return jsonify({"error": "array_name is required"}), 400

    url = f"http://{ip}:8081/array-initial-config"
    body_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="PATCH"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return jsonify({"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")})
    except urllib.error.HTTPError as e:
        return jsonify({"status": e.code, "body": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


# ── ZTE FlashArray Erasure ────────────────────────────────────────────────────

@app.route("/zte-login", methods=["POST"])
def zte_login():
    data = request.get_json(force=True)
    vip = data.get("vip", "").strip()
    api_token = data.get("api_token", "").strip()
    if not vip or not api_token:
        return jsonify({"error": "VIP and API token required"}), 400

    url = f"https://{vip}/api/login"
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("api-token", api_token)
    req.add_header("Content-Length", "0")

    try:
        with urllib.request.urlopen(req, timeout=15, context=_zte_ssl) as resp:
            session_token = resp.getheader("x-auth-token")
            if not session_token:
                return jsonify({"error": "No x-auth-token in response"}), 500
            return jsonify({"session_token": session_token})
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"}), e.code
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/zte-erasure-status", methods=["POST"])
def zte_erasure_status():
    data = request.get_json(force=True)
    vip = data.get("vip", "").strip()
    version = data.get("api_version", "2.56").strip()
    session_token = data.get("session_token", "").strip()
    if not vip or not session_token:
        return jsonify({"ok": False, "error": "VIP and session token required"}), 400

    url = f"https://{vip}/api/{version}/arrays/erasures"
    req = urllib.request.Request(url, method="GET")
    req.add_header("x-auth-token", session_token)

    try:
        with urllib.request.urlopen(req, timeout=15, context=_zte_ssl) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return jsonify({"ok": True, "data": body})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return jsonify({"ok": False, "error": f"HTTP {e.code}", "body": body})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/zte-start-wipe", methods=["POST"])
def zte_start_wipe():
    data = request.get_json(force=True)
    vip = data.get("vip", "").strip()
    version = data.get("api_version", "2.56").strip()
    session_token = data.get("session_token", "").strip()
    skip_phonehome = bool(data.get("skip_phonehome_check", False))
    if not vip or not session_token:
        return jsonify({"error": "VIP and session token required"}), 400

    skip_val = "true" if skip_phonehome else "false"
    url = (f"https://{vip}/api/{version}/arrays/erasures"
           f"?eradicate_all_data=true&preserve_configuration_data=all"
           f"&skip_phonehome_check={skip_val}")
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("x-auth-token", session_token)
    req.add_header("Content-Length", "0")

    try:
        with urllib.request.urlopen(req, timeout=30, context=_zte_ssl) as resp:
            return jsonify({"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")})
    except urllib.error.HTTPError as e:
        return jsonify({"status": e.code, "body": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/zte-finalize", methods=["POST"])
def zte_finalize():
    data = request.get_json(force=True)
    vip = data.get("vip", "").strip()
    version = data.get("api_version", "2.56").strip()
    session_token = data.get("session_token", "").strip()
    image_source = data.get("image_source", "auto").strip() or "auto"
    if not vip or not session_token:
        return jsonify({"error": "VIP and session token required"}), 400

    payload = {
        "finalize": True,
        "eradicate_all_data": True,
        "reinstall_image": True,
        "delete_sanitization_certificate": True,
        "image_source": image_source,
    }
    body_bytes = json.dumps(payload).encode()
    url = f"https://{vip}/api/{version}/arrays/erasures"
    req = urllib.request.Request(url, data=body_bytes, method="PATCH")
    req.add_header("x-auth-token", session_token)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30, context=_zte_ssl) as resp:
            return jsonify({"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")})
    except urllib.error.HTTPError as e:
        return jsonify({"status": e.code, "body": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/zte-cancel", methods=["POST"])
def zte_cancel():
    data = request.get_json(force=True)
    vip = data.get("vip", "").strip()
    version = data.get("api_version", "2.56").strip()
    session_token = data.get("session_token", "").strip()
    if not vip or not session_token:
        return jsonify({"error": "VIP and session token required"}), 400

    url = f"https://{vip}/api/{version}/arrays/erasures"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("x-auth-token", session_token)

    try:
        with urllib.request.urlopen(req, timeout=15, context=_zte_ssl) as resp:
            return jsonify({"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")})
    except urllib.error.HTTPError as e:
        return jsonify({"status": e.code, "body": e.read().decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"error": str(e)})


DHCP_CONF    = Path("/etc/dnsmasq.d/ztp-dhcp.conf")
DHCP_PID     = Path("/var/run/ztp-dnsmasq.pid")
DHCP_LEASES  = Path("/var/lib/dnsmasq/dnsmasq.leases")
DHCP_STATE   = Path("/tmp/ztp-dhcp-state.json")


def _dhcp_running():
    if not DHCP_PID.exists():
        return False
    try:
        pid = int(DHCP_PID.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def _dhcp_read_state():
    try:
        return json.loads(DHCP_STATE.read_text())
    except Exception:
        return {}


def _dhcp_write_state(cfg):
    DHCP_STATE.write_text(json.dumps(cfg))


def _dhcp_write_conf(cfg):
    DHCP_LEASES.parent.mkdir(parents=True, exist_ok=True)
    conf = (
        f"interface={cfg['interface']}\n"
        f"bind-interfaces\n"
        f"dhcp-range={cfg['range_start']},{cfg['range_end']},60m\n"
        f"dhcp-leasefile={DHCP_LEASES}\n"
        f"port=0\n"
        f"no-resolv\n"
        f"no-hosts\n"
        f"dhcp-option=3\n"
        f"dhcp-option=6\n"
    )
    DHCP_CONF.parent.mkdir(parents=True, exist_ok=True)
    DHCP_CONF.write_text(conf)


def _ip_addr_add(ip_cidr, iface):
    import subprocess
    subprocess.run(["ip", "addr", "add", ip_cidr, "dev", iface],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ip_addr_del(ip_cidr, iface):
    import subprocess
    subprocess.run(["ip", "addr", "del", ip_cidr, "dev", iface],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _dhcp_stop_proc():
    state = _dhcp_read_state()
    if state.get("server_ip") and state.get("interface"):
        _ip_addr_del(state["server_ip"], state["interface"])
    if not DHCP_PID.exists():
        return
    try:
        pid = int(DHCP_PID.read_text().strip())
        os.kill(pid, 15)
    except Exception:
        pass
    try:
        DHCP_PID.unlink()
    except Exception:
        pass


def _dhcp_start_proc():
    import subprocess
    proc = subprocess.Popen(
        ["dnsmasq", "--conf-file=" + str(DHCP_CONF), "--no-daemon",
         "--log-facility=/tmp/ztp-dnsmasq.log"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    DHCP_PID.parent.mkdir(parents=True, exist_ok=True)
    DHCP_PID.write_text(str(proc.pid))
    return proc.pid


@app.route("/dhcp-interfaces", methods=["GET"])
def dhcp_interfaces():
    import subprocess, re
    _SKIP = {"lo"}
    _SKIP_PREFIX = ("docker", "br-", "veth")

    def _parse_brief(out):
        ifaces = []
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            if name in _SKIP or any(name.startswith(p) for p in _SKIP_PREFIX):
                continue
            addrs = [a for a in parts[2:] if not a.startswith("fe80")]
            ifaces.append({"name": name, "addresses": addrs})
        return ifaces

    def _parse_full(out):
        # Parse `ip addr show` (non-brief) output
        ifaces = []
        current = None
        for line in out.splitlines():
            m = re.match(r'^\d+:\s+(\S+?)[@:]?\s', line)
            if m:
                name = m.group(1)
                if name in _SKIP or any(name.startswith(p) for p in _SKIP_PREFIX):
                    current = None
                else:
                    current = {"name": name, "addresses": []}
                    ifaces.append(current)
            elif current and "inet " in line:
                m2 = re.search(r'inet (\S+)', line)
                if m2 and not m2.group(1).startswith("fe80"):
                    current["addresses"].append(m2.group(1))
        return ifaces

    try:
        try:
            out = subprocess.check_output(["ip", "-br", "addr", "show"],
                                          text=True, stderr=subprocess.DEVNULL,
                                          timeout=5)
            ifaces = _parse_brief(out)
        except Exception:
            out = subprocess.check_output(["ip", "addr", "show"],
                                          text=True, stderr=subprocess.DEVNULL,
                                          timeout=5)
            ifaces = _parse_full(out)
        return jsonify({"interfaces": ifaces})
    except Exception as e:
        return jsonify({"interfaces": [], "error": str(e)})


@app.route("/dhcp-status", methods=["GET"])
def dhcp_status():
    running = _dhcp_running()
    state = _dhcp_read_state()
    return jsonify({"running": running, "config": state if state else None})


@app.route("/dhcp-start", methods=["POST"])
def dhcp_start():
    data = request.get_json(force=True)
    iface       = data.get("interface", "").strip()
    subnet      = data.get("subnet", "").strip()
    range_start = data.get("range_start", "").strip()
    range_end   = data.get("range_end", "").strip()
    server_ip   = data.get("server_ip", "").strip()

    if not all([iface, subnet, range_start, range_end, server_ip]):
        return jsonify({"error": "interface, subnet, range_start, range_end, and server_ip are required"}), 400

    cfg = {"interface": iface, "subnet": subnet,
           "range_start": range_start, "range_end": range_end, "server_ip": server_ip}

    if _dhcp_running():
        _dhcp_stop_proc()

    try:
        _dhcp_write_conf(cfg)
        _ip_addr_add(server_ip, iface)
        _dhcp_start_proc()
        _dhcp_write_state(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/dhcp-stop", methods=["POST"])
def dhcp_stop():
    try:
        _dhcp_stop_proc()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/dhcp-restart", methods=["POST"])
def dhcp_restart():
    try:
        _dhcp_stop_proc()
        if not DHCP_CONF.exists():
            return jsonify({"error": "No DHCP config found. Start the server first."}), 400
        _dhcp_start_proc()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/dhcp-leases", methods=["GET"])
def dhcp_leases():
    leases = []
    try:
        if DHCP_LEASES.exists():
            import datetime
            for line in DHCP_LEASES.read_text().splitlines():
                parts = line.strip().split()
                if len(parts) >= 4:
                    ts, mac, ip, hostname = parts[0], parts[1], parts[2], parts[3]
                    try:
                        expiry = datetime.datetime.fromtimestamp(
                            int(ts)).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        expiry = ts
                    leases.append({
                        "ip": ip, "mac": mac,
                        "hostname": hostname if hostname != "*" else "",
                        "expiry": expiry
                    })
    except Exception as e:
        return jsonify({"leases": [], "error": str(e)})
    return jsonify({"leases": leases})


@app.route("/dhcp-logs", methods=["GET"])
def dhcp_logs():
    log_file = Path("/tmp/ztp-dnsmasq.log")
    try:
        if log_file.exists():
            lines = log_file.read_text().splitlines()
            return jsonify({"lines": lines[-100:]})
        return jsonify({"lines": []})
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)})


if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8080, debug=False)
