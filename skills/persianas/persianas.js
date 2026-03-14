#!/usr/bin/env node
/**
 * Skill: Persianas — CLI
 * Control de persianas motorizadas via API ZWave IoT
 *
 * Uso:
 *   node persianas.js --device "Ventana Salon" --action on
 *   node persianas.js --device "Puerta Salon" --action off
 *   node persianas.js --device "ZWayVDev_zway_4-0-38" --action stop
 *   node persianas.js --all --action off
 */

const API_URL = process.env.PERSIANAS_API_URL || 'https://northr3nd.duckdns.org';
const API_TOKEN = process.env.PERSIANAS_API_TOKEN || null;

const DEVICE_MAPPING = {
  'Ventana Hab. Principal': 'ZWayVDev_zway_3-0-38',
  'Puerta Hab. Principal':  'ZWayVDev_zway_8-0-38',
  'Ventana Salon':          'ZWayVDev_zway_4-0-38',
  'Ventana Salón':          'ZWayVDev_zway_4-0-38',
  'Puerta Salon':           'ZWayVDev_zway_2-0-38',
  'Puerta Salón':           'ZWayVDev_zway_2-0-38',
  'Ventana Ordenadores':    'ZWayVDev_zway_7-0-38',
  'Ventana Hab. Jaume/Edu': 'ZWayVDev_zway_9-0-38',
};

const VALID_ACTIONS = ['on', 'off', 'stop'];

function normalize(s) {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function resolveDeviceId(device) {
  if (DEVICE_MAPPING[device]) return DEVICE_MAPPING[device];
  const key = Object.keys(DEVICE_MAPPING).find((k) => normalize(k) === normalize(device));
  if (key) return DEVICE_MAPPING[key];
  if (device.startsWith('ZWayVDev_')) return device;
  return null;
}

async function sendCommand(deviceId, action) {
  const url = `${API_URL}/api/devices/${deviceId}/command/${action}`;
  const headers = { 'Content-Type': 'application/json' };
  if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`;

  const res = await fetch(url, { method: 'POST', headers });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--all') { args.all = true; continue; }
    if (argv[i].startsWith('--') && argv[i + 1]) {
      args[argv[i].slice(2)] = argv[++i];
    }
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const { action, device, all } = args;

  if (!action || !VALID_ACTIONS.includes(action)) {
    console.error(`Error: --action debe ser uno de: ${VALID_ACTIONS.join(', ')}`);
    process.exit(1);
  }

  const actionLabel = { on: 'subida (abierta)', off: 'bajada (cerrada)', stop: 'detenida' }[action];

  if (all) {
    const seen = new Set();
    const errors = [];
    for (const [name, deviceId] of Object.entries(DEVICE_MAPPING)) {
      if (seen.has(deviceId)) continue;
      seen.add(deviceId);
      try {
        await sendCommand(deviceId, action);
        console.log(`OK  ${name} → ${actionLabel}`);
      } catch (err) {
        console.error(`ERR ${name}: ${err.message}`);
        errors.push(name);
      }
    }
    if (errors.length) {
      console.error(`\nFallaron ${errors.length} persiana(s): ${errors.join(', ')}`);
      process.exit(1);
    }
    console.log(`\nTodas las persianas ${actionLabel}s correctamente.`);
    return;
  }

  if (!device) {
    const names = Object.keys(DEVICE_MAPPING).filter((k, i, arr) =>
      arr.findIndex((x) => DEVICE_MAPPING[x] === DEVICE_MAPPING[k]) === i
    );
    console.error(`Error: especifica --device <nombre> o --all`);
    console.error(`Dispositivos disponibles:\n${names.map((n) => `  - ${n}`).join('\n')}`);
    process.exit(1);
  }

  const deviceId = resolveDeviceId(device);
  if (!deviceId) {
    const names = Object.keys(DEVICE_MAPPING).filter((k, i, arr) =>
      arr.findIndex((x) => DEVICE_MAPPING[x] === DEVICE_MAPPING[k]) === i
    );
    console.error(`Error: dispositivo desconocido "${device}"`);
    console.error(`Disponibles:\n${names.map((n) => `  - ${n}`).join('\n')}`);
    process.exit(1);
  }

  try {
    await sendCommand(deviceId, action);
    console.log(`OK: "${device}" ${actionLabel}`);
  } catch (err) {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  }
}

main();
