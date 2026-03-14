---
name: persianas
description: "Controla las persianas motorizadas de la casa via API ZWave. Usa cuando el usuario pida subir, bajar, abrir, cerrar o parar persianas o puertas motorizadas. NO usar para: luces, temperatura, alarmas u otros dispositivos."
homepage: https://northr3nd.duckdns.org
metadata:
  {
    "openclaw":
      {
        "emoji": "🪟",
        "requires": { "bins": ["node"] },
      },
  }
---

# Persianas

Controla las persianas motorizadas de la casa.

## Cuando usar esta skill

Usar cuando el usuario pida:
- Subir, bajar, abrir, cerrar o parar una persiana o puerta motorizada
- Controlar todas las persianas a la vez

## Dispositivos disponibles

| Nombre | ID ZWave |
|--------|----------|
| Ventana Hab. Principal | ZWayVDev_zway_3-0-38 |
| Puerta Hab. Principal  | ZWayVDev_zway_8-0-38 |
| Ventana Salon          | ZWayVDev_zway_4-0-38 |
| Puerta Salon           | ZWayVDev_zway_2-0-38 |
| Ventana Ordenadores    | ZWayVDev_zway_7-0-38 |
| Ventana Hab. Jaume/Edu | ZWayVDev_zway_9-0-38 |

## Acciones

- `on`   → Sube / abre la persiana
- `off`  → Baja / cierra la persiana
- `stop` → Detiene el movimiento

## Comandos

### Controlar una persiana individual

```bash
node {baseDir}/persianas.js --device "Ventana Salon" --action on
```

```bash
node {baseDir}/persianas.js --device "Puerta Hab. Principal" --action off
```

```bash
node {baseDir}/persianas.js --device "Ventana Ordenadores" --action stop
```

### Controlar todas las persianas a la vez

```bash
node {baseDir}/persianas.js --all --action off
```

```bash
node {baseDir}/persianas.js --all --action on
```

## Notas

- El argumento `--device` acepta el nombre descriptivo (con o sin tilde) o el ID ZWave directo.
- Si el usuario dice "sube" o "abre" → usar `on`; "baja" o "cierra" → `off`; "para" → `stop`.
- Para securizar en el futuro: configura la variable de entorno `PERSIANAS_API_TOKEN` con el Bearer token.
