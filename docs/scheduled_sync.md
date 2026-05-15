# Scheduled Sync

La app soporta sincronizacion programada en segundo plano sin depender de tareas internas de FastAPI. Los jobs se ejecutan como comandos Python y pueden ser llamados desde `systemd timer` o `cron`.

## Jobs disponibles

### Morning health

Comando:

```bash
python -m app.jobs.sync_morning_health
```

Que hace:

- recorre atletas activos con Garmin configurado
- sincroniza salud de ayer y hoy
- recalcula readiness del dia actual
- genera `HealthAiAnalysis` de hoy solo si faltaba, salvo `--force`
- guarda un `ScheduledSyncJobLog`

Argumentos opcionales:

```bash
python -m app.jobs.sync_morning_health --athlete-id 1 --date 2026-05-14 --force
```

### Evening full

Comando:

```bash
python -m app.jobs.sync_evening_full
```

Que hace:

- recorre atletas activos con Garmin configurado
- sincroniza actividades nuevas desde la ultima actividad guardada hasta hoy
- sincroniza salud de hoy y ayer
- intenta vincular actividades nuevas con sesiones planificadas
- genera analisis V2 faltantes para actividades vinculadas
- recalcula readiness del dia
- actualiza `WeeklyAnalysis` de la semana actual cuando corresponde
- guarda un `ScheduledSyncJobLog`

Argumentos opcionales:

```bash
python -m app.jobs.sync_evening_full --athlete-id 1 --date 2026-05-14 --force
```

### Resolve pending

Comando:

```bash
python -m app.jobs.resolve_pending_items
```

Que hace:

- detecta pendientes activos o faltantes para el atleta
- intenta resolverlos sin duplicar datos ni analisis
- marca `resolved` cuando la situacion ya quedo cubierta
- incrementa intentos y deja trazabilidad si el pendiente sigue abierto
- guarda un `ScheduledSyncJobLog`

Argumentos opcionales:

```bash
python -m app.jobs.resolve_pending_items --athlete-id 1 --date 2026-05-14 --force
python -m app.jobs.resolve_pending_items --athlete-id 1 --dry-run
```

## Prueba manual

Desde el VPS:

```bash
cd /home/pablo/ProyectoGarmin
source .venv/bin/activate
python -m app.jobs.sync_morning_health --date 2026-05-14
python -m app.jobs.sync_evening_full --date 2026-05-14
python -m app.jobs.resolve_pending_items --date 2026-05-14
```

Cada comando imprime un resumen JSON apto para `journalctl`.

## Systemd timers

Archivos de ejemplo:

- `docs/systemd/training_sync_morning.service`
- `docs/systemd/training_sync_morning.timer`
- `docs/systemd/training_sync_evening.service`
- `docs/systemd/training_sync_evening.timer`
- `docs/systemd/training_resolve_pending.service`
- `docs/systemd/training_resolve_pending.timer`

Instalacion sugerida:

```bash
sudo cp docs/systemd/training_sync_*.service /etc/systemd/system/
sudo cp docs/systemd/training_sync_*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now training_sync_morning.timer
sudo systemctl enable --now training_sync_evening.timer
sudo systemctl enable --now training_resolve_pending.timer
systemctl list-timers
```

## Logs con journalctl

```bash
journalctl -u training_sync_morning.service -n 100 --no-pager
journalctl -u training_sync_evening.service -n 100 --no-pager
journalctl -u training_resolve_pending.service -n 100 --no-pager
journalctl -fu training_sync_morning.service
journalctl -fu training_sync_evening.service
journalctl -fu training_resolve_pending.service
```

## Desactivar timers

```bash
sudo systemctl disable --now training_sync_morning.timer
sudo systemctl disable --now training_sync_evening.timer
sudo systemctl disable --now training_resolve_pending.timer
```

## Notas operativas

- Hay lock anti-duplicacion por tipo de job.
- Si existe una corrida `running` reciente, la nueva se registra como `skipped`.
- Si una corrida `running` supera 2 horas, se considera stale y se permite una nueva.
- El procesamiento es independiente por atleta. Un fallo parcial deja el job global como `partial_success`.
- Todas las marcas de tiempo se guardan en UTC y se muestran en la zona horaria configurada de la app o del atleta.
- La sincronizacion manual desde la UI sigue disponible como fallback.
