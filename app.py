#!/usr/bin/env python3
"""Simple file server with upload, download, delete, and folder creation."""

import os
import json
import shutil
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from flask import (
    Flask, request, send_from_directory, redirect, url_for,
    render_template_string, flash, abort, jsonify
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path(os.environ.get("FILE_SERVER_ROOT", "/home/atcadmin/fileserver/files"))

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zero Touch Provisioning (ZTP) for FlashArray and FlashBlade</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
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

<!-- ZTP PureSoftwareInstall -->
<div class="card mt-3">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#ztpInstall">
    <span class="fw-semibold"><i class="bi bi-lightning-charge text-warning me-1"></i> ZTP PureSoftwareInstall</span>
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
          <label class="form-label fw-semibold">Controller 1 (bottom controller) eth0/eth4 ZTP IP</label>
          <input type="text" id="ztpIp" class="form-control" placeholder="192.168.1.100">
          <div class="form-text">Port 8081 is used automatically. From a console connection, look for it under <code>ps_eth0@br_eth0</code> (or <code>4</code>) when running <code>ip a</code>.</div>
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
          <button class="btn btn-outline-secondary fw-semibold" onclick="runZtpStatus(this)">
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


<!-- ZTP PureInitialize FlashArray -->
<div class="card mt-3">
  <div class="card-header d-flex justify-content-between align-items-center"
       style="cursor:pointer" data-bs-toggle="collapse" data-bs-target="#ztpInitCollapse">
    <span class="fw-semibold"><i class="bi bi-hdd-rack text-info me-1"></i> ZTP PureInitialize FlashArray</span>
    <i class="bi bi-chevron-down"></i>
  </div>
  <div class="collapse" id="ztpInitCollapse">
    <div class="card-body">
      <p class="text-muted small mb-3">
        <i class="bi bi-info-circle me-1"></i>
        Sends initial configuration to a FlashArray via a PATCH request to <code>http://[ct1.eth0 IP]:8081/array-initial-config</code>.
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
          <label class="form-label fw-semibold">Controller 1 (bottom controller) eth0/eth4 ZTP IP</label>
          <input type="text" id="initIp" class="form-control" placeholder="192.168.1.100">
          <div class="form-text">Port 8081 is used automatically. From a console connection, look for it under <code>ps_eth0@br_eth0</code> (or <code>4</code>) when running <code>ip a</code>.</div>
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

        <div class="col-12 d-flex gap-2 flex-wrap">
          <button class="btn btn-info fw-semibold text-white" onclick="runZtpInitialize(this)">
            <i class="bi bi-hdd-rack me-1"></i> Send Initialize Config
          </button>
          <button class="btn btn-outline-info fw-semibold" onclick="previewInitPayload()">
            <i class="bi bi-eye me-1"></i> Preview JSON
          </button>
          <button class="btn btn-outline-secondary fw-semibold" onclick="downloadInitPayload()">
            <i class="bi bi-download me-1"></i> Download JSON
          </button>
        </div>
      </div>

      <!-- Payload preview -->
      <div id="initPayloadPreview" class="mt-3 d-none">
        <hr>
        <div class="d-flex align-items-center justify-content-between mb-2">
          <span class="fw-semibold">Payload Preview</span>
          <button class="btn btn-sm btn-outline-secondary" onclick="downloadInitPayload()">
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

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
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

async function runZtpStatus(btn) {
  const ip = document.getElementById('ztpIp').value.trim();
  if (!ip) { alert('Enter the Controller 1 ZTP IP first.'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Checking…';

  try {
    const resp = await fetch('/ztp-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip })
    });
    const data = await resp.json();

    const panel = document.getElementById('ztpStatusPanel');
    panel.classList.remove('d-none');

    const status = data.status || '';
    const phaseIdx = ZTP_PHASES.findIndex(p => p.key === status);
    const phase = ZTP_PHASES[phaseIdx] || { label: status || 'Unknown', desc: data.error || '' };

    const badge = document.getElementById('ztpPhaseBadge');
    badge.textContent = phase.label;
    const isComplete = status === 'install-complete';
    const isError = !data.status;
    badge.className = 'badge fs-6 ' + (isError ? 'bg-danger' : isComplete ? 'bg-success' : status === 'install-not-started' ? 'bg-secondary' : 'bg-primary');

    document.getElementById('ztpPhaseDesc').textContent = phase.desc;

    // Step bubbles
    const stepsEl = document.getElementById('ztpSteps');
    stepsEl.innerHTML = ZTP_PHASES.map((p, i) => {
      const done = phaseIdx >= 0 && i < phaseIdx;
      const active = i === phaseIdx;
      const cls = done ? 'bg-success text-white' : active ? 'bg-primary text-white' : 'bg-light text-muted border';
      return `<span class="badge rounded-pill px-3 py-2 ${cls}" style="font-size:0.8rem">${done ? '✓ ' : ''}${p.label}</span>`;
    }).join('');

    // Errors
    const errBlock = document.getElementById('ztpErrorsBlock');
    const errors = data.errors;
    if (errors && errors.length) {
      errBlock.classList.remove('d-none');
      document.getElementById('ztpErrorsBody').textContent = JSON.stringify(errors, null, 2);
    } else {
      errBlock.classList.add('d-none');
    }

    document.getElementById('ztpCompleteNote').classList.toggle('d-none', !isComplete);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i> Check Status';
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

function buildInitPayload() {
  const ip        = document.getElementById('initIp').value.trim();
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

  if (!ip || !arrayName || !ct0addr || !ct0mask || !ct0gw ||
      !ct1addr || !ct1mask || !ct1gw || !viraddr || !virmask || !virgw || !ntp || !tz) {
    alert('All required fields must be filled in.'); return null;
  }
  if (!dnsDomain || !dnsNs) {
    alert('DNS Domain and Nameservers are required.'); return null;
  }
  if (!smtpRelay || !smtpSender) {
    alert('SMTP Relay Host and Sender Domain are required.'); return null;
  }
  if (!document.getElementById('initEulaAccepted').checked) {
    alert('You must accept the EULA to proceed.'); return null;
  }
  const eulaName  = document.getElementById('initEulaName').value.trim();
  const eulaTitle = document.getElementById('initEulaTitle').value.trim();
  const eulaOrg   = document.getElementById('initEulaOrg').value.trim();
  if (!eulaName || !eulaTitle || !eulaOrg) {
    alert('EULA full name, job title, and organization are required.'); return null;
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

  return { ip, payload };
}

function previewInitPayload() {
  const result = buildInitPayload();
  if (!result) return;
  const preview = document.getElementById('initPayloadPreview');
  preview.classList.remove('d-none');
  document.getElementById('initPayloadBody').textContent = JSON.stringify(result.payload, null, 2);
  preview.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function downloadInitPayload() {
  const result = buildInitPayload();
  if (!result) return;
  const blob = new Blob([JSON.stringify(result.payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `initialize-config-${result.payload.array_name || 'flasharray'}.json`;
  a.click();
  URL.revokeObjectURL(url);
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

function copyLink(btn, relPath) {
  const url = window.location.origin + '/download/' + relPath;
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


if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8080, debug=False)
