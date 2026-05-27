# sheets_sync.py -- Google Sheets integration via Apps Script Web App
# No gspread/google-auth required.
# Setup:
#   1. Open the Google Sheets -> Extensions -> Apps Script
#   2. Paste Code.gs, deploy as Web App (Execute as: Me, Access: Anyone)
#   3. Copy the /exec URL
#   4. Set env var APPS_SCRIPT_URL=<url> in Render

import os
import json
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

SPREADSHEET_ID = "1UEr6ybpTcYHD68N7A8UwxVNHELkbXlGbGhXXEhzAo5o"


# ---------------------------------------------------------------
# HTTP TRANSPORT
# ---------------------------------------------------------------
def _get_script_url():
    return os.environ.get("APPS_SCRIPT_URL", "").strip()


def is_configured():
    """Return True if APPS_SCRIPT_URL env var is set."""
    return bool(_get_script_url())


def _call(action, data, timeout=30):
    """
    POST JSON to the Apps Script Web App.
    Apps Script /exec returns 302 -> must follow redirect keeping POST method.
    allow_redirects=True in requests converts POST to GET on 302 -> doPost never fires.
    Fix: follow redirects manually keeping POST for every hop (max 5).
    """
    url = _get_script_url()
    if not url:
        return {"ok": False, "error": "APPS_SCRIPT_URL not set"}

    payload = json.dumps({"action": action, "data": data})

    # --- Try requests first: manual redirect to preserve POST ---
    try:
        import requests as _req
        target = url
        for _ in range(5):
            resp = _req.post(
                target,
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
                allow_redirects=False   # CRITICAL: do NOT auto-follow
            )
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "").strip()
                if not location:
                    return {"ok": False, "error": "Redirect with no Location header"}
                target = location
                continue
            resp.raise_for_status()
            return resp.json()
        return {"ok": False, "error": "Too many redirects"}
    except ImportError:
        pass  # Fall through to urllib
    except Exception as exc:
        log.error("sheets_sync._call(requests) error: %s", exc)
        return {"ok": False, "error": str(exc)}

    # --- urllib fallback: manual POST redirect ---
    import urllib.request
    import urllib.error

    payload_bytes = payload.encode("utf-8")
    headers = {"Content-Type": "application/json"}

    def _post(target_url):
        req = urllib.request.Request(
            target_url,
            data=payload_bytes,
            headers=headers,
            method="POST"
        )
        return req

    try:
        target = url
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
            urllib.request.HTTPRedirectHandler.__new__(
                type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                     {"redirect_request": lambda self, *a, **kw: None})
            )
        )
        for _ in range(5):
            try:
                with opener.open(_post(target), timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code in (301, 302, 303, 307, 308):
                    location = err.headers.get("Location", "").strip()
                    if not location:
                        return {"ok": False, "error": "Redirect with no Location"}
                    target = location
                    continue
                raise
        return {"ok": False, "error": "Too many redirects (urllib)"}
    except Exception as exc:
        log.error("sheets_sync._call(urllib) error: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------
# SYNC: TECHNICIANS
# ---------------------------------------------------------------
def sync_technicians():
    from models import Technician
    techs = Technician.query.order_by(Technician.name).all()
    headers = ["ID", "Nombre", "Turno_Fijo", "Solo_Tickets", "Sin_Domingos", "Activo"]
    rows = [
        [t.id, t.name, t.fixed_shift or "Auto",
         "Si" if t.tickets_only else "No",
         "Si" if t.no_sundays else "No",
         "Si" if t.is_active else "No"]
        for t in techs
    ]
    result = _call("sync_technicians", {"headers": headers, "rows": rows})
    log.info("sheets_sync: Tecnicos -> %s", result)
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC: MONTHLY SCHEDULE
# ---------------------------------------------------------------
def sync_month(year, month):
    import calendar
    from models import (Technician, DayAssignment,
                        SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO)

    _, n_days = calendar.monthrange(year, month)
    dates = [date(year, month, d) for d in range(1, n_days + 1)]

    month_start = date(year, month, 1)
    month_end   = date(year, month, n_days)
    das = (DayAssignment.query
           .filter(DayAssignment.date >= month_start,
                   DayAssignment.date <= month_end)
           .all())
    da_map = {(da.technician_id, da.date): da for da in das}

    techs = (Technician.query
             .filter_by(is_active=True)
             .order_by(Technician.name).all())

    shift_label = {
        SHIFT_T1: "T1", SHIFT_T2: "T2",
        SHIFT_DOMINGO: "DOM", SHIFT_DESCANSO: "DESC",
    }

    day_headers = [f"{d.day:02d}/{d.month:02d}" for d in dates]
    headers = ["Tecnico"] + day_headers

    rows = []
    for t in techs:
        row = [t.name]
        for d in dates:
            da = da_map.get((t.id, d))
            if da is None:
                row.append("")
            else:
                if da.is_sunday_holiday:
                    label = "DOM" if d.weekday() == 6 else "FEST"
                else:
                    label = shift_label.get(da.shift, da.shift or "")
                if da.is_ticket:
                    label += "+TK"
                row.append(label)
        rows.append(row)

    result = _call("sync_month", {
        "year": year, "month": month,
        "headers": headers, "rows": rows
    })
    log.info("sheets_sync: Horario_%d_%02d -> %s", year, month, result)
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC: DOMINICALES
# ---------------------------------------------------------------
def sync_dominicales(year, month):
    import calendar
    from models import Technician, DayAssignment

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
            stats[tid] = {"name": t.name if t else "?",
                          "sundays": 0, "festivos": 0}
        if da.date.weekday() == 6:
            stats[tid]["sundays"] += 1
        else:
            stats[tid]["festivos"] += 1

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    headers = ["Anio", "Mes", "Tecnico", "Domingos", "Festivos", "Total", "Sync"]
    rows = [
        [year, month, s["name"],
         s["sundays"], s["festivos"],
         s["sundays"] + s["festivos"], now_str]
        for s in stats.values()
    ]

    result = _call("sync_dominicales", {"headers": headers, "rows": rows})
    log.info("sheets_sync: Dominicales -> %s", result)
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC: NOVELTIES
# ---------------------------------------------------------------
def sync_novelties(year, month):
    import calendar
    from models import Novelty, Technician

    _, n_days = calendar.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, n_days)

    novs = (Novelty.query
            .filter(Novelty.date_start <= month_end,
                    Novelty.date_end >= month_start)
            .order_by(Novelty.date_start).all())

    headers = ["Anio", "Mes", "Tecnico", "Tipo",
               "Fecha_Inicio", "Fecha_Fin", "Nota"]
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

    result = _call("sync_novelties", {"headers": headers, "rows": rows})
    log.info("sheets_sync: Novedades -> %s", result)
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC: CONFIG
# ---------------------------------------------------------------
def sync_config():
    from models import Config
    cfgs = Config.query.order_by(Config.key).all()
    desc_map = {
        "MIN_T2_DAILY":   "Minimo tecnicos T2 por dia",
        "TICKET_COUNT":   "Tecnicos en turno tickets por semana",
        "sunday_workers": "Tecnicos por domingo/festivo (default 6)",
    }
    headers = ["Clave", "Valor", "Descripcion"]
    rows = [[c.key, c.value, desc_map.get(c.key, "")] for c in cfgs]
    result = _call("sync_config", {"headers": headers, "rows": rows})
    log.info("sheets_sync: Config -> %s", result)
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC: LOG
# ---------------------------------------------------------------
def sync_log(action, detail=""):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = _call("append_log", {"row": [now_str, action, detail]})
    return result.get("ok", False)


# ---------------------------------------------------------------
# SYNC ALL
# ---------------------------------------------------------------
def sync_all(year, month):
    """
    Full sync for a given year/month. Called after generate_month().
    Returns dict with per-module results.
    """
    if not is_configured():
        log.info("sheets_sync: APPS_SCRIPT_URL not set, skipping")
        return {"configured": False}

    results = {"configured": True}
    results["technicians"] = sync_technicians()
    results["month"]       = sync_month(year, month)
    results["dominicales"] = sync_dominicales(year, month)
    results["novelties"]   = sync_novelties(year, month)
    results["config"]      = sync_config()
    summary = ", ".join(
        f"{k}={'OK' if v else 'FAIL'}"
        for k, v in results.items() if k != "configured"
    )
    results["log"] = sync_log("sync_all", f"{year}-{month:02d}: {summary}")
    log.info("sheets_sync: sync_all done %d-%02d: %s", year, month, results)
    return results
