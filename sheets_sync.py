# sheets_sync.py -- Google Sheets integration for soporte-turnos
# Requires: gspread>=6.0.0, google-auth>=2.0.0
# Setup: set env var GOOGLE_CREDENTIALS_JSON with service account JSON content
#        Share the spreadsheet with the service account email

import os
import json
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

SPREADSHEET_ID = "1UEr6ybpTcYHD68N7A8UwxVNHELkbXlGbGhXXEhzAo5o"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# ---------------------------------------------------------------
# CLIENT
# ---------------------------------------------------------------
def _get_client():
    """Return an authenticated gspread client, or None if not configured."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_json:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as exc:
        log.error("sheets_sync: auth failed: %s", exc)
        return None


def is_configured():
    """Return True if GOOGLE_CREDENTIALS_JSON env var is set."""
    return bool(os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip())


def _get_spreadsheet(client):
    try:
        return client.open_by_key(SPREADSHEET_ID)
    except Exception as exc:
        log.error("sheets_sync: cannot open spreadsheet: %s", exc)
        return None


def _get_or_create_sheet(ss, name, rows=2000, cols=40):
    """Return worksheet by name, creating it if needed."""
    try:
        return ss.worksheet(name)
    except Exception:
        try:
            return ss.add_worksheet(title=name, rows=rows, cols=cols)
        except Exception as exc:
            log.error("sheets_sync: cannot create sheet %s: %s", name, exc)
            return None


def _write_rows(ws, headers, data_rows):
    """Clear sheet and write headers + data rows."""
    try:
        ws.clear()
        all_rows = [headers] + [
            [str(v) if v is not None else "" for v in row]
            for row in data_rows
        ]
        ws.update(all_rows, value_input_option="USER_ENTERED")
        return True
    except Exception as exc:
        log.error("sheets_sync: write_rows failed: %s", exc)
        return False


def _append_row(ws, row):
    """Append a single row to the sheet."""
    try:
        ws.append_row(
            [str(v) if v is not None else "" for v in row],
            value_input_option="USER_ENTERED"
        )
        return True
    except Exception as exc:
        log.error("sheets_sync: append_row failed: %s", exc)
        return False


# ---------------------------------------------------------------
# SYNC: TECHNICIANS
# ---------------------------------------------------------------
def sync_technicians():
    """Push all technicians to 'Tecnicos' sheet."""
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    from models import Technician, SHIFT_T1, SHIFT_T2
    ws = _get_or_create_sheet(ss, "Tecnicos")
    if not ws:
        return False

    techs = Technician.query.order_by(Technician.name).all()
    headers = ["ID", "Nombre", "Turno_Fijo", "Solo_Tickets", "Sin_Domingos", "Activo"]
    rows = []
    for t in techs:
        rows.append([
            t.id,
            t.name,
            t.fixed_shift or "Auto",
            "Si" if t.tickets_only else "No",
            "Si" if t.no_sundays else "No",
            "Si" if t.is_active else "No",
        ])
    ok = _write_rows(ws, headers, rows)
    log.info("sheets_sync: Tecnicos synced (%d rows)", len(rows))
    return ok


# ---------------------------------------------------------------
# SYNC: MONTHLY SCHEDULE
# ---------------------------------------------------------------
def sync_month(year, month):
    """
    Push full monthly schedule matrix to 'Horario_YYYY_MM' sheet.
    Rows = technicians, columns = days of month.
    """
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    import calendar
    from models import (Technician, WeekSchedule, DayAssignment,
                        SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO)

    sheet_name = f"Horario_{year}_{month:02d}"
    ws = _get_or_create_sheet(ss, sheet_name)
    if not ws:
        return False

    # Build date range for the month
    _, n_days = calendar.monthrange(year, month)
    dates = [date(year, month, d) for d in range(1, n_days + 1)]

    # Fetch all assignments for the month
    month_start = date(year, month, 1)
    month_end   = date(year, month, n_days)
    das = (DayAssignment.query
           .filter(DayAssignment.date >= month_start,
                   DayAssignment.date <= month_end)
           .all())
    # Index by (tech_id, date)
    da_map = {(da.technician_id, da.date): da for da in das}

    techs = (Technician.query
             .filter_by(is_active=True)
             .order_by(Technician.name).all())

    day_labels = [f"{d.day:02d}/{d.month:02d}" for d in dates]
    headers = ["Tecnico"] + day_labels

    shift_label = {
        SHIFT_T1: "T1",
        SHIFT_T2: "T2",
        SHIFT_DOMINGO: "DOM",
        SHIFT_DESCANSO: "DESC",
    }

    rows = []
    for t in techs:
        row = [t.name]
        for d in dates:
            da = da_map.get((t.id, d))
            if da is None:
                row.append("")
            else:
                label = shift_label.get(da.shift, da.shift or "")
                if da.is_ticket:
                    label += "+TK"
                if da.is_sunday_holiday:
                    label = "DOM" if d.weekday() == 6 else "FEST"
                row.append(label)
        rows.append(row)

    ok = _write_rows(ws, headers, rows)
    log.info("sheets_sync: %s synced (%d techs, %d days)", sheet_name, len(techs), n_days)
    return ok


# ---------------------------------------------------------------
# SYNC: DOMINICALES (dom/fest per tech per month)
# ---------------------------------------------------------------
def sync_dominicales(year, month):
    """Push sunday/festivo stats to 'Dominicales' sheet (append mode)."""
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    import calendar
    from models import Technician, DayAssignment, SHIFT_DOMINGO

    ws = _get_or_create_sheet(ss, "Dominicales")
    if not ws:
        return False

    _, n_days = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, n_days)

    das = (DayAssignment.query
           .filter(DayAssignment.date >= month_start,
                   DayAssignment.date <= month_end,
                   DayAssignment.is_sunday_holiday == True)
           .all())

    stats = {}
    for da in das:
        tid = da.technician_id
        if tid not in stats:
            t = Technician.query.get(tid)
            stats[tid] = {
                'name': t.name if t else '?',
                'sundays': 0, 'festivos': 0
            }
        if da.date.weekday() == 6:
            stats[tid]['sundays'] += 1
        else:
            stats[tid]['festivos'] += 1

    # Check if headers exist (first row)
    try:
        first = ws.row_values(1)
    except Exception:
        first = []

    if not first:
        ws.append_row(
            ["Anio", "Mes", "Tecnico", "Domingos", "Festivos", "Total", "Sync"],
            value_input_option="USER_ENTERED"
        )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for tid, s in stats.items():
        _append_row(ws, [
            year, month, s['name'],
            s['sundays'], s['festivos'],
            s['sundays'] + s['festivos'],
            now_str,
        ])

    log.info("sheets_sync: Dominicales appended %d rows for %d-%02d", len(stats), year, month)
    return True


# ---------------------------------------------------------------
# SYNC: NOVELTIES
# ---------------------------------------------------------------
def sync_novelties(year, month):
    """Push novelties (active during the month) to 'Novedades' sheet."""
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    import calendar
    from models import Novelty, Technician

    ws = _get_or_create_sheet(ss, "Novedades")
    if not ws:
        return False

    _, n_days = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, n_days)

    novs = (Novelty.query
            .filter(Novelty.date_start <= month_end,
                    Novelty.date_end >= month_start)
            .order_by(Novelty.date_start).all())

    headers = ["Anio", "Mes", "Tecnico", "Tipo", "Fecha_Inicio", "Fecha_Fin", "Nota"]
    rows = []
    for n in novs:
        t = Technician.query.get(n.technician_id)
        rows.append([
            year, month,
            t.name if t else str(n.technician_id),
            n.novelty_type,
            n.date_start.strftime("%Y-%m-%d"),
            n.date_end.strftime("%Y-%m-%d"),
            n.note or "",
        ])

    ok = _write_rows(ws, headers, rows)
    log.info("sheets_sync: Novedades synced (%d rows)", len(rows))
    return ok


# ---------------------------------------------------------------
# SYNC: LOGS
# ---------------------------------------------------------------
def sync_log(action, detail=""):
    """Append a single log entry to 'Logs' sheet."""
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    ws = _get_or_create_sheet(ss, "Logs")
    if not ws:
        return False

    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first:
        ws.append_row(
            ["Timestamp", "Accion", "Detalle"],
            value_input_option="USER_ENTERED"
        )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return _append_row(ws, [now_str, action, detail])


# ---------------------------------------------------------------
# SYNC: CONFIGURATION
# ---------------------------------------------------------------
def sync_config():
    """Push current Config keys to 'Configuracion' sheet."""
    client = _get_client()
    if not client:
        return False
    ss = _get_spreadsheet(client)
    if not ss:
        return False

    from models import Config

    ws = _get_or_create_sheet(ss, "Configuracion")
    if not ws:
        return False

    cfgs = Config.query.order_by(Config.key).all()
    headers = ["Clave", "Valor", "Descripcion"]
    desc_map = {
        "MIN_T2_DAILY":    "Minimo tecnicos T2 por dia",
        "TICKET_COUNT":    "Tecnicos en turno tickets por semana",
        "sunday_workers":  "Tecnicos por domingo/festivo (default 6)",
    }
    rows = []
    for c in cfgs:
        rows.append([c.key, c.value, desc_map.get(c.key, "")])

    ok = _write_rows(ws, headers, rows)
    log.info("sheets_sync: Configuracion synced")
    return ok


# ---------------------------------------------------------------
# SYNC ALL
# ---------------------------------------------------------------
def sync_all(year, month):
    """
    Run full sync for a given year/month.
    Called automatically after generate_month().
    Returns dict with per-module results.
    """
    if not is_configured():
        log.info("sheets_sync: GOOGLE_CREDENTIALS_JSON not set, skipping sync")
        return {"configured": False}

    results = {"configured": True}
    results["technicians"] = sync_technicians()
    results["month"]       = sync_month(year, month)
    results["dominicales"] = sync_dominicales(year, month)
    results["novelties"]   = sync_novelties(year, month)
    results["config"]      = sync_config()
    results["log"]         = sync_log(
        "sync_all",
        f"Full sync {year}-{month:02d}: " +
        ", ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in results.items()
                  if k != "configured")
    )
    log.info("sheets_sync: sync_all done for %d-%02d: %s", year, month, results)
    return results
