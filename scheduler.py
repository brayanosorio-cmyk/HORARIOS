# scheduler.py -- Algoritmo de generacion de horarios v3
# Soporta: generacion semanal, generacion mensual, festivos Colombia automaticos
import calendar as cal_module
from datetime import date, timedelta, datetime
from collections import defaultdict
from models import (db, Technician, WeekSchedule, DayAssignment,
                    Novelty, TechnicianHistory, HolidayCalendar, Config,
                    MonthSchedule,
                    SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO, NOVEDADES)

DEFAULT_MIN_T2     = 6
DEFAULT_TICKET_COUNT = 5
HOLIDAY_SHIFT      = SHIFT_DOMINGO


# ---------------------------------------------------------------
# CONFIG HELPERS
# ---------------------------------------------------------------
def get_config_int(key, default):
    val = Config.get(key)
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_week_dates(week_start):
    return [week_start + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------
# COLOMBIA OFFICIAL HOLIDAYS
# ---------------------------------------------------------------
# Fixed holidays (never move)
_FIXED_HOL = [
    ((1,  1),  "Ano Nuevo"),
    ((5,  1),  "Dia del Trabajo"),
    ((7,  20), "Grito de Independencia"),
    ((8,  7),  "Batalla de Boyaca"),
    ((12, 8),  "Inmaculada Concepcion"),
    ((12, 25), "Navidad"),
]

# Movable holidays (se trasladan al siguiente lunes)
_MOVABLE_HOL = [
    ((1,  6),  "Reyes Magos"),
    ((3,  19), "San Jose"),
    ((6,  29), "San Pedro y San Pablo"),
    ((8,  15), "Asuncion de la Virgen"),
    ((10, 12), "Dia de la Raza"),
    ((11, 1),  "Todos los Santos"),
    ((11, 11), "Independencia de Cartagena"),
]


def _next_monday(d):
    """Return d if it is already Monday, otherwise the next Monday."""
    dow = d.weekday()  # 0 = Monday
    if dow == 0:
        return d
    return d + timedelta(days=(7 - dow))


def _easter(year):
    """Compute Easter Sunday (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_colombia_holidays(year):
    """
    Returns dict {date: name} with all official Colombian public holidays.
    Handles fixed, movable (next Monday), and Easter-relative holidays.
    """
    result = {}

    # Fixed
    for (m, d), name in _FIXED_HOL:
        result[date(year, m, d)] = name

    # Movable
    for (m, d), name in _MOVABLE_HOL:
        h = date(year, m, d)
        result[_next_monday(h)] = name

    # Easter-relative
    easter = _easter(year)
    result[easter - timedelta(days=3)] = "Jueves Santo"
    result[easter - timedelta(days=2)] = "Viernes Santo"

    asc = _next_monday(easter + timedelta(days=39))
    result[asc] = "Ascension del Senor"

    corp = _next_monday(easter + timedelta(days=60))
    result[corp] = "Corpus Christi"

    sac = _next_monday(easter + timedelta(days=68))
    result[sac] = "Sagrado Corazon"

    return result


def seed_colombia_holidays(year):
    """Seeds HolidayCalendar table with Colombia holidays. Idempotent."""
    holidays = get_colombia_holidays(year)
    added = 0
    for d, name in holidays.items():
        if not HolidayCalendar.query.filter_by(date=d).first():
            db.session.add(HolidayCalendar(date=d, name=name))
            added += 1
    if added:
        db.session.commit()
    return added


# ---------------------------------------------------------------
# HOLIDAY CHECK (uses DB + Colombia cache)
# ---------------------------------------------------------------
_holiday_cache = {}  # {year: set of dates}


def _load_holiday_cache(year):
    if year not in _holiday_cache:
        rows = HolidayCalendar.query.all()
        by_year = defaultdict(set)
        for r in rows:
            by_year[r.date.year].add(r.date)
        # Merge all years loaded
        for y, s in by_year.items():
            _holiday_cache[y] = s
        if year not in _holiday_cache:
            _holiday_cache[year] = set()


def is_holiday(d):
    return HolidayCalendar.query.filter_by(date=d).first() is not None


def is_sunday_or_holiday(d):
    return d.weekday() == 6 or is_holiday(d)


# ---------------------------------------------------------------
# MONTH HELPERS
# ---------------------------------------------------------------
def get_month_mondays(year, month):
    """
    Returns list of Mondays whose 7-day week overlaps the given month.
    Example: for February 2026, includes the Monday of the week
    containing Feb 1 (even if that Monday is in January).
    """
    _, days_in = cal_module.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, days_in)

    # First Monday: Monday of the week containing month_start
    first_monday = month_start - timedelta(days=month_start.weekday())

    mondays = []
    monday = first_monday
    while monday <= month_end:
        mondays.append(monday)
        monday += timedelta(days=7)
    return mondays


def get_month_days(year, month):
    """Returns list of all calendar dates in the month."""
    _, days_in = cal_module.monthrange(year, month)
    return [date(year, month, d) for d in range(1, days_in + 1)]


# ---------------------------------------------------------------
# HISTORY SUMMARY
# ---------------------------------------------------------------
def get_tech_history_summary(tech_id):
    rows = (TechnicianHistory.query
            .filter_by(technician_id=tech_id)
            .order_by(TechnicianHistory.week_start.desc()).all())
    if not rows:
        return {"t2_weeks": 0, "ticket_weeks": 0, "sundays": 0,
                "last_t2": None, "last_ticket": None,
                "last_shift": None, "consecutive_sundays": 0}
    total_t2  = sum(1 for r in rows if r.shift_assigned == SHIFT_T2)
    total_tk  = sum(1 for r in rows if r.was_ticket_week)
    total_sun = sum(r.sunday_count for r in rows)
    consec_sun = 0
    if rows[0].sunday_count > 0:
        consec_sun = 1
        if len(rows) > 1 and rows[1].sunday_count > 0:
            consec_sun = 2
    return {
        "t2_weeks":    total_t2,
        "ticket_weeks": total_tk,
        "sundays":     total_sun,
        "last_t2":     next((r.week_start for r in rows if r.shift_assigned == SHIFT_T2), None),
        "last_ticket": next((r.week_start for r in rows if r.was_ticket_week), None),
        "last_shift":  rows[0].shift_assigned,
        "consecutive_sundays": consec_sun,
    }


# ---------------------------------------------------------------
# SCORING FUNCTIONS
# ---------------------------------------------------------------
def _t2_score(tech, history, week_start):
    if tech.fixed_shift == SHIFT_T1 or tech.tickets_only:
        return 9999.0
    if tech.fixed_shift == SHIFT_T2:
        return -9999.0
    score = float(history["t2_weeks"]) * 10.0
    if history["last_t2"] and (week_start - history["last_t2"]).days <= 7:
        score += 5.0
    return score


def _ticket_score(tech, history):
    if tech.fixed_shift == SHIFT_T2:
        return 9999.0
    if tech.tickets_only:
        return -9999.0
    return float(history["ticket_weeks"]) * 10.0


def _get_sunday_workers_count():
    """Return configured number of techs per sunday/festivo (default 6)."""
    return get_config_int('sunday_workers', 6)


def _get_window_context(d, days=14):
    """
    Rolling window: how many special days (dom/fest) each tech worked
    in the [d-days, d) range. Used to enforce short-term rotation rest.
    Returns {tech_id: {'count': N}}.
    """
    window_start = d - timedelta(days=days)
    das = (DayAssignment.query
           .filter(DayAssignment.date >= window_start,
                   DayAssignment.date < d,
                   DayAssignment.is_sunday_holiday == True)
           .all())
    ctx = {}
    for da in das:
        tid = da.technician_id
        if tid not in ctx:
            ctx[tid] = {'count': 0}
        ctx[tid]['count'] += 1
    return ctx


def _sunday_score(tech, history, d=None, month_ctx=None, window_ctx=None):
    """
    Score for assigning tech to a special day (sunday or festivo).
    Lower score = higher priority (picked first).

    Scoring layers:
      1. All-time cumulative (sundays field = dom + fest combined)
      2. Monthly balance: penalise same-type repetition heavily
      3. Cross-type penalty: penalise dom after fest and vice-versa
      4. 14-day window: strongest short-term rest enforcement
    """
    if tech.no_sundays:
        return 9999.0
    if history["consecutive_sundays"] >= 1:
        return 8888.0
    # Layer 1: all-time load (dom+fest unified)
    score = float(history["sundays"]) * 10.0
    if d is not None and month_ctx is not None:
        ctx = month_ctx.get(tech.id, {'sundays': 0, 'festivos': 0})
        is_sunday = (d.weekday() == 6)
        if is_sunday:
            score += ctx['sundays']  * 60.0   # same type (dom) this month
            score += ctx['festivos'] * 35.0   # cross type (fest) this month
        else:
            score += ctx['festivos'] * 60.0   # same type (fest) this month
            score += ctx['sundays']  * 35.0   # cross type (dom) this month
    # Layer 3: 14-day rolling window (strongest penalty)
    if d is not None and window_ctx is not None:
        wctx = window_ctx.get(tech.id, {'count': 0})
        score += wctx['count'] * 80.0
    return score


# ---------------------------------------------------------------
# MONTH SPECIAL DAY CONTEXT  (v6: balance domingo/festivo)
# ---------------------------------------------------------------
def _get_month_special_context(week_start):
    """
    Returns {tech_id: {'sundays': N, 'festivos': N}} for sunday_holiday
    assignments already generated in the same month as week_start,
    but only for dates BEFORE week_start.
    Used to enforce monthly sunday/festivo rotation balance.
    """
    month_start = date(week_start.year, week_start.month, 1)
    das = (DayAssignment.query
           .filter(DayAssignment.date >= month_start,
                   DayAssignment.date < week_start,
                   DayAssignment.is_sunday_holiday == True)
           .all())
    ctx = {}
    for da in das:
        if da.technician_id not in ctx:
            ctx[da.technician_id] = {'sundays': 0, 'festivos': 0}
        if da.date.weekday() == 6:
            ctx[da.technician_id]['sundays'] += 1
        else:
            ctx[da.technician_id]['festivos'] += 1
    return ctx


# ---------------------------------------------------------------
# GENERATE WEEK
# ---------------------------------------------------------------
def generate_week(week_start, force_regenerate=False,
                  forced_t2_ids=None, forced_ticket_ids=None):
    """
    Genera el horario de una semana.
    forced_t2_ids: lista de IDs a forzar en T2 (override manual)
    forced_ticket_ids: lista de IDs a forzar como tickets (override manual)
    """
    if week_start.weekday() != 0:
        raise ValueError("week_start debe ser lunes")

    MIN_T2       = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
    TICKET_COUNT = get_config_int("TICKET_COUNT", DEFAULT_TICKET_COUNT)
    week_end     = week_start + timedelta(days=6)
    week_dates   = get_week_dates(week_start)

    existing = WeekSchedule.query.filter_by(week_start=week_start).first()
    if existing:
        if not force_regenerate:
            raise ValueError("Semana ya generada. Activa 'forzar regeneracion'.")
        if existing.is_locked:
            raise ValueError("Semana bloqueada. Desbloquea antes de regenerar.")
        DayAssignment.query.filter_by(week_id=existing.id).delete()
        week_obj = existing
        week_obj.generated_at = datetime.utcnow()
    else:
        week_obj = WeekSchedule(week_start=week_start, week_end=week_end)
        db.session.add(week_obj)
        db.session.flush()

    technicians = Technician.query.filter_by(is_active=True).all()
    if not technicians:
        raise ValueError("No hay tecnicos activos.")

    # Novedades de la semana (rangos)
    novelties_map = defaultdict(dict)
    week_novelties = Novelty.query.filter(
        Novelty.date_start <= week_end,
        Novelty.date_end   >= week_start
    ).all()
    for nov in week_novelties:
        d = nov.date_start
        while d <= nov.date_end and d <= week_end:
            if d >= week_start:
                novelties_map[nov.technician_id][d] = nov.novelty_type
            d += timedelta(days=1)

    histories = {t.id: get_tech_history_summary(t.id) for t in technicians}
    warnings  = []

    # --- Asignar turnos semanales ---
    tech_week_shift = {}

    # Fijos primero
    for tech in technicians:
        if tech.fixed_shift in (SHIFT_T1, SHIFT_T2):
            tech_week_shift[tech.id] = tech.fixed_shift

    # Forzados manualmente
    if forced_t2_ids:
        for tid in forced_t2_ids:
            tech_week_shift[tid] = SHIFT_T2

    # tickets_only siempre T1
    for tech in technicians:
        if tech.tickets_only and tech.id not in tech_week_shift:
            tech_week_shift[tech.id] = SHIFT_T1

    # Rotacion automatica
    fixed_t2_count = sum(1 for v in tech_week_shift.values() if v == SHIFT_T2)
    needed_t2 = max(0, MIN_T2 - fixed_t2_count)

    free_techs = [t for t in technicians if t.id not in tech_week_shift]
    free_techs.sort(key=lambda t: _t2_score(t, histories[t.id], week_start))

    assigned_t2 = 0
    for tech in free_techs:
        if assigned_t2 < needed_t2 and tech.fixed_shift != SHIFT_T1:
            tech_week_shift[tech.id] = SHIFT_T2
            assigned_t2 += 1
        else:
            tech_week_shift[tech.id] = SHIFT_T1

    total_t2 = sum(1 for v in tech_week_shift.values() if v == SHIFT_T2)
    if total_t2 < MIN_T2:
        warnings.append(f"Solo {total_t2} en T2 (minimo {MIN_T2})")

    # --- Tickets ---
    ticket_assigned = set()
    if forced_ticket_ids:
        ticket_assigned = set(forced_ticket_ids)

    t1_techs = [t for t in technicians if tech_week_shift.get(t.id) == SHIFT_T1]
    if len(ticket_assigned) < TICKET_COUNT:
        for t in t1_techs:
            if t.tickets_only and t.id not in ticket_assigned and len(ticket_assigned) < TICKET_COUNT:
                ticket_assigned.add(t.id)
        rotateable = [t for t in t1_techs if not t.tickets_only and t.id not in ticket_assigned]
        rotateable.sort(key=lambda t: _ticket_score(t, histories[t.id]))
        for t in rotateable:
            if len(ticket_assigned) >= TICKET_COUNT:
                break
            ticket_assigned.add(t.id)

    # --- Dominicales y Festivos (balance mensual v6) ---
    special_days = [d for d in week_dates if is_sunday_or_holiday(d)]
    month_ctx = _get_month_special_context(week_start)
    sunday_assignments = {}
    for sd in special_days:
        sd_is_sunday = (sd.weekday() == 6)
        # Pool 1: sin consecutivo y respetando balance mensual dom/fest
        eligible = []
        for t in technicians:
            if t.no_sundays:
                continue
            if novelties_map[t.id].get(sd) is not None:
                continue
            if histories[t.id]["consecutive_sundays"] >= 1:
                continue
            ctx = month_ctx.get(t.id, {'sundays': 0, 'festivos': 0})
            if sd_is_sunday and ctx['sundays'] >= 1:
                continue   # Ya trabajo un domingo este mes: no asignar otro domingo
            if not sd_is_sunday and ctx['festivos'] >= 1:
                continue   # Ya trabajo un festivo este mes: no asignar otro festivo
            eligible.append(t)
        # Fallback 1: relaxar regla mensual dom/fest (todos rotaron)
        if not eligible:
            for t in technicians:
                if t.no_sundays or novelties_map[t.id].get(sd) is not None:
                    continue
                if histories[t.id]["consecutive_sundays"] >= 1:
                    continue
                eligible.append(t)
            if eligible:
                warnings.append(f"Dia {sd.day}: todos los elegibles ya rotaron este mes")
        # Fallback 2: relaxar consecutivo tambien
        if not eligible:
            eligible = [t for t in technicians
                        if not t.no_sundays and novelties_map[t.id].get(sd) is None]
            if eligible:
                warnings.append(f"Dia {sd.day}: sin restricciones (fallback 2)")
        window_ctx = _get_window_context(sd)
        eligible.sort(key=lambda t: _sunday_score(t, histories[t.id], sd, month_ctx, window_ctx))
        n_workers = _get_sunday_workers_count()
        count = min(n_workers, max(1, len(eligible)))
        sunday_assignments[sd] = [t.id for t in eligible[:count]]

    # --- Descanso post-domingo (v6) ---
    # Sabado de esta semana = Monday + 5 dias
    saturday_this_week = week_start + timedelta(days=5)
    # Domingo de la semana anterior = Monday - 1 dia
    prev_sunday = week_start - timedelta(days=1)  # Siempre sera domingo
    prev_sunday_workers = set()
    if prev_sunday.weekday() == 6:  # Verificacion defensiva
        prev_sun_das = DayAssignment.query.filter(
            DayAssignment.date == prev_sunday,
            DayAssignment.is_sunday_holiday == True,
            DayAssignment.shift == SHIFT_DOMINGO
        ).all()
        prev_sunday_workers = {da.technician_id for da in prev_sun_das}

    # --- Crear asignaciones dia x dia ---
    assignments = []
    for tech in technicians:
        base_shift = tech_week_shift.get(tech.id, SHIFT_T1)
        is_ticket_tech = tech.id in ticket_assigned

        for d in week_dates:
            nov_type = novelties_map[tech.id].get(d)
            if is_sunday_or_holiday(d):
                if nov_type:
                    shift = nov_type
                elif tech.id in sunday_assignments.get(d, []):
                    shift = HOLIDAY_SHIFT
                else:
                    shift = SHIFT_DESCANSO
                da = DayAssignment(week_id=week_obj.id, technician_id=tech.id,
                                   date=d, shift=shift, is_ticket=False,
                                   is_sunday_holiday=(shift == HOLIDAY_SHIFT))
            elif nov_type:
                da = DayAssignment(week_id=week_obj.id, technician_id=tech.id,
                                   date=d, shift=nov_type, is_ticket=False)
            else:
                # Regla descanso post-domingo: si trabajo domingo previo, descanso sabado
                if (d == saturday_this_week
                        and tech.id in prev_sunday_workers
                        and not nov_type):
                    da = DayAssignment(week_id=week_obj.id, technician_id=tech.id,
                                       date=d, shift=SHIFT_DESCANSO,
                                       is_ticket=False, is_manual=False,
                                       override_reason="Descanso post-domingo automatico")
                else:
                    da = DayAssignment(week_id=week_obj.id, technician_id=tech.id,
                                       date=d, shift=base_shift,
                                       is_ticket=(is_ticket_tech and d.weekday() < 5))
            assignments.append(da)

    for da in assignments:
        db.session.add(da)

    # --- Historial ---
    for tech in technicians:
        w_shift  = tech_week_shift.get(tech.id, SHIFT_T1)
        was_tk   = tech.id in ticket_assigned
        sun_cnt  = sum(1 for d in week_dates
                       if is_sunday_or_holiday(d)
                       and tech.id in sunday_assignments.get(d, [])
                       and novelties_map[tech.id].get(d) is None)
        had_nov  = any(novelties_map[tech.id].values())
        prev     = histories[tech.id]

        hist = TechnicianHistory.query.filter_by(
            technician_id=tech.id, week_start=week_start).first()
        if not hist:
            hist = TechnicianHistory(technician_id=tech.id, week_start=week_start)
            db.session.add(hist)
        hist.shift_assigned     = w_shift
        hist.was_ticket_week    = was_tk
        hist.sunday_count       = sun_cnt
        hist.had_novelty        = had_nov
        hist.total_t2_weeks     = prev["t2_weeks"]     + (1 if w_shift == SHIFT_T2 else 0)
        hist.total_ticket_weeks = prev["ticket_weeks"] + (1 if was_tk else 0)
        hist.total_sundays      = prev["sundays"]      + sun_cnt

    db.session.commit()
    return {
        "week_id":      week_obj.id,
        "week_start":   week_start.isoformat(),
        "week_end":     week_end.isoformat(),
        "assignments":  [a.to_dict() for a in assignments],
        "warnings":     warnings,
        "t2_count":     total_t2,
        "ticket_count": len(ticket_assigned),
    }


# ---------------------------------------------------------------
# GENERATE MONTH (CORE: planificacion mensual)
# ---------------------------------------------------------------
def generate_month(year, month, force_regenerate=False,
                   forced_t2_ids=None, forced_ticket_ids=None):
    """
    Genera el horario completo de un mes.
    - Auto-siembra festivos Colombia para el ano.
    - Genera cada semana que tenga al menos un dia en el mes.
    - Semanas compartidas entre meses se generan la primera vez;
      la segunda vez se omiten salvo force_regenerate=True.
    - Respeta bloqueo de mes.
    """
    # Auto-seed Colombia holidays
    seed_colombia_holidays(year)
    # Also seed next year if month is December (avoid missing Jan 1)
    if month == 12:
        seed_colombia_holidays(year + 1)

    # Check month lock
    ms = MonthSchedule.query.filter_by(year=year, month=month).first()
    if ms and ms.is_locked and not force_regenerate:
        raise ValueError(f"Mes {year}-{month:02d} bloqueado. Desbloquea antes de regenerar.")

    mondays = get_month_mondays(year, month)

    results  = []
    warnings = []
    skipped  = 0

    for monday in mondays:
        try:
            result = generate_week(
                monday,
                force_regenerate=force_regenerate,
                forced_t2_ids=forced_t2_ids,
                forced_ticket_ids=forced_ticket_ids,
            )
            results.append(result)
            warnings.extend(result.get("warnings", []))
        except ValueError as e:
            msg = str(e)
            if "ya generada" in msg:
                skipped += 1
                warnings.append(f"Semana {monday} ya existe (compartida, omitida)")
            elif "bloqueada" in msg.lower():
                skipped += 1
                warnings.append(f"Semana {monday} bloqueada (omitida)")
            else:
                raise

    # Create / update MonthSchedule record
    if not ms:
        ms = MonthSchedule(year=year, month=month)
        db.session.add(ms)
    ms.generated_at = datetime.utcnow()
    db.session.commit()

    total_t2_sum = sum(r.get("t2_count", 0) for r in results)

    return {
        "year":             year,
        "month":            month,
        "month_id":         ms.id,
        "weeks_generated":  len(results),
        "weeks_skipped":    skipped,
        "total_t2":         total_t2_sum,
        "warnings":         warnings,
    }


# ---------------------------------------------------------------
# NOVELTY RANGE
# ---------------------------------------------------------------
def apply_novelty_range(technician_id, date_start, date_end, novelty_type, notes=""):
    """Registra novedad por rango de fechas y actualiza asignaciones existentes."""
    warnings = []

    # Eliminar novedades solapadas
    existing = Novelty.query.filter(
        Novelty.technician_id == technician_id,
        Novelty.date_start <= date_end,
        Novelty.date_end   >= date_start
    ).all()
    for e in existing:
        db.session.delete(e)

    nov = Novelty(technician_id=technician_id, date_start=date_start,
                  date_end=date_end, novelty_type=novelty_type, notes=notes)
    db.session.add(nov)

    # Actualizar DayAssignments existentes en el rango
    d = date_start
    while d <= date_end:
        da = DayAssignment.query.filter_by(technician_id=technician_id, date=d).first()
        if da:
            old = da.shift
            da.shift = novelty_type
            da.is_ticket = False
            da.is_manual = True
            da.override_reason = f"Novedad: {novelty_type}"
            da.modified_at = datetime.utcnow()
            if old == SHIFT_T2:
                t2_left = DayAssignment.query.filter(
                    DayAssignment.week_id == da.week_id,
                    DayAssignment.date    == d,
                    DayAssignment.shift   == SHIFT_T2,
                    DayAssignment.technician_id != technician_id
                ).count()
                min_t2 = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
                if t2_left < min_t2:
                    warnings.append(f"T2 bajo minimo el {d} ({t2_left}/{min_t2})")
        d += timedelta(days=1)

    db.session.commit()
    return {"success": True, "warnings": warnings}


# ---------------------------------------------------------------
# STATS
# ---------------------------------------------------------------
def get_week_stats(week_id):
    assignments = DayAssignment.query.filter_by(week_id=week_id).all()
    if not assignments:
        return {}
    from collections import Counter
    by_date = defaultdict(Counter)
    for a in assignments:
        by_date[a.date.isoformat()][a.shift] += 1
    min_t2 = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
    t2_by_day = {d: c.get(SHIFT_T2, 0) for d, c in by_date.items()}
    return {
        "t2_by_day":       t2_by_day,
        "min_t2":          min(t2_by_day.values()) if t2_by_day else 0,
        "tickets_total":   sum(1 for a in assignments if a.is_ticket),
        "total_assignments": len(assignments),
        "min_t2_config":   min_t2,
    }


def get_month_stats(year, month):
    """Aggregate stats for a full month."""
    mondays = get_month_mondays(year, month)
    month_days = get_month_days(year, month)
    month_day_set = set(month_days)

    # Get all week IDs for this month
    week_ids = []
    for monday in mondays:
        wk = WeekSchedule.query.filter_by(week_start=monday).first()
        if wk:
            week_ids.append(wk.id)

    if not week_ids:
        return {"generated": False}

    # Only assignments falling within the month's days
    all_assignments = []
    for wk_id in week_ids:
        das = DayAssignment.query.filter_by(week_id=wk_id).all()
        for da in das:
            if da.date in month_day_set:
                all_assignments.append(da)

    from collections import Counter
    by_date = defaultdict(Counter)
    for a in all_assignments:
        by_date[a.date][a.shift] += 1

    min_t2_cfg = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
    t2_by_day = {d: by_date[d].get(SHIFT_T2, 0) for d in month_days}
    low_t2_days = [d for d, v in t2_by_day.items() if v < min_t2_cfg and not is_sunday_or_holiday(d)]

    return {
        "generated":     True,
        "t2_by_day":     t2_by_day,
        "low_t2_days":   low_t2_days,
        "tickets_total": sum(1 for a in all_assignments if a.is_ticket),
        "novelties_total": sum(1 for a in all_assignments if a.shift in NOVEDADES),
        "min_t2_config": min_t2_cfg,
        "days_with_t2_ok": sum(1 for v in t2_by_day.values() if v >= min_t2_cfg),
    }


# ---------------------------------------------------------------
# OPERATIONAL ALERTS  (v5)
# ---------------------------------------------------------------
def get_alerts(year, month):
    """
    Compute operational alerts for a given month.
    Returns list of dicts: {type, code, msg, detail}
    type: 'danger' | 'warning' | 'info'
    """
    alerts = []
    mondays = get_month_mondays(year, month)
    month_days = get_month_days(year, month)
    month_day_set = set(month_days)
    min_t2 = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)

    # Build week map
    week_map = {}
    for monday in mondays:
        wk = WeekSchedule.query.filter_by(week_start=monday).first()
        if wk:
            week_map[monday] = wk

    if not week_map:
        return []

    # All assignments in month only
    all_das = []
    for wk in week_map.values():
        das = DayAssignment.query.filter_by(week_id=wk.id).all()
        for da in das:
            if da.date in month_day_set:
                all_das.append(da)

    if not all_das:
        return []

    # --- 1. Low T2 days ---
    by_date_shift = defaultdict(lambda: defaultdict(int))
    for da in all_das:
        by_date_shift[da.date][da.shift] += 1

    low_t2_days = []
    zero_t2_days = []
    for d in month_days:
        if is_sunday_or_holiday(d):
            continue
        if not by_date_shift[d]:
            continue  # No assignments at all (not generated)
        t2_count = by_date_shift[d].get(SHIFT_T2, 0)
        if t2_count == 0:
            zero_t2_days.append(d)
        elif t2_count < min_t2:
            low_t2_days.append(d)

    if zero_t2_days:
        days_str = ", ".join(str(d.day) for d in zero_t2_days[:6])
        if len(zero_t2_days) > 6:
            days_str += "..."
        alerts.append({
            "type": "danger", "code": "zero_t2",
            "msg": f"Sin T2 asignado: dias {days_str}",
            "detail": f"Critico: {len(zero_t2_days)} dia(s) sin cobertura T2"
        })

    if low_t2_days:
        days_str = ", ".join(str(d.day) for d in low_t2_days[:6])
        if len(low_t2_days) > 6:
            days_str += "..."
        alerts.append({
            "type": "warning", "code": "low_t2",
            "msg": f"T2 bajo minimo ({min_t2}): dias {days_str}",
            "detail": f"{len(low_t2_days)} dia(s) con T2 insuficiente"
        })

    # --- 2. T2 overload: tech in T2 3+ weeks of same month ---
    tech_t2_week_count = defaultdict(int)
    for monday, wk in week_map.items():
        week_das = [da for da in all_das
                    if da.date >= monday and da.date <= monday + timedelta(days=6)]
        t2_ids = {da.technician_id for da in week_das if da.shift == SHIFT_T2}
        for tid in t2_ids:
            tech_t2_week_count[tid] += 1

    overloaded = [(tid, cnt) for tid, cnt in tech_t2_week_count.items() if cnt >= 3]
    if overloaded:
        names = []
        for tid, cnt in overloaded[:3]:
            tech = Technician.query.get(tid)
            if tech:
                names.append(f"{tech.name}({cnt}sem)")
        extra = len(overloaded) - 3
        names_str = ", ".join(names)
        if extra > 0:
            names_str += f" y {extra} mas"
        alerts.append({
            "type": "warning", "code": "t2_overload",
            "msg": f"Sobre-rotacion T2: {names_str}",
            "detail": "Considera redistribuir carga de T2 en el mes"
        })

    # --- 3. Consecutive sundays/holidays ---
    tech_sunday_weeks = defaultdict(int)
    for monday, wk in week_map.items():
        week_das = [da for da in all_das
                    if da.date >= monday and da.date <= monday + timedelta(days=6)]
        sun_ids = {da.technician_id for da in week_das if da.is_sunday_holiday}
        for tid in sun_ids:
            tech_sunday_weeks[tid] += 1

    consec_sun = [(tid, cnt) for tid, cnt in tech_sunday_weeks.items() if cnt >= 2]
    if consec_sun:
        names = []
        for tid, cnt in consec_sun[:3]:
            tech = Technician.query.get(tid)
            if tech:
                names.append(tech.name)
        extra = len(consec_sun) - 3
        names_str = ", ".join(names)
        if extra > 0:
            names_str += f" y {extra} mas"
        alerts.append({
            "type": "info", "code": "consec_sunday",
            "msg": f"Dominicales repetidos: {names_str}",
            "detail": "Tecnicos con 2+ domingos/festivos en el mes"
        })

    # --- 4. Novelty conflict: registered after generation ---
    novelties = Novelty.query.filter(
        Novelty.date_start <= month_days[-1],
        Novelty.date_end   >= month_days[0]
    ).all()

    nov_map = defaultdict(dict)
    for nov in novelties:
        d = nov.date_start
        while d <= nov.date_end:
            if d in month_day_set:
                nov_map[nov.technician_id][d] = nov.novelty_type
            d += timedelta(days=1)

    conflict_techs = set()
    for da in all_das:
        if da.is_manual:
            continue
        nov_type = nov_map[da.technician_id].get(da.date)
        if nov_type and da.shift not in NOVEDADES and da.shift not in (SHIFT_DESCANSO, SHIFT_DOMINGO):
            conflict_techs.add(da.technician_id)

    if conflict_techs:
        names = []
        for tid in list(conflict_techs)[:3]:
            tech = Technician.query.get(tid)
            if tech:
                names.append(tech.name)
        extra = len(conflict_techs) - 3
        names_str = ", ".join(names)
        if extra > 0:
            names_str += f" y {extra} mas"
        alerts.append({
            "type": "warning", "code": "novelty_conflict",
            "msg": f"Novedad sin reflejar en horario: {names_str}",
            "detail": "Hay novedades registradas DESPUES de generar. Regenera el mes."
        })

    # --- 5. Unassigned days check ---
    days_no_data = [d for d in month_days
                    if not is_sunday_or_holiday(d) and not by_date_shift[d]]
    if days_no_data:
        alerts.append({
            "type": "info", "code": "unassigned",
            "msg": f"{len(days_no_data)} dia(s) sin datos de asignacion",
            "detail": "Puede haber dias sin generar dentro del mes"
        })

    # --- 6. Too many sundays for one tech ---
    tech_sunday_count = {}
    tech_festivo_count = {}
    for da in all_das:
        if not da.is_sunday_holiday or da.shift != SHIFT_DOMINGO:
            continue
        if da.date.weekday() == 6:
            tech_sunday_count[da.technician_id] = tech_sunday_count.get(da.technician_id, 0) + 1
        else:
            tech_festivo_count[da.technician_id] = tech_festivo_count.get(da.technician_id, 0) + 1

    heavy_sundays = [(tid, cnt) for tid, cnt in tech_sunday_count.items() if cnt >= 2]
    if heavy_sundays:
        names = []
        for tid, cnt in heavy_sundays[:3]:
            tech = Technician.query.get(tid)
            if tech:
                names.append(f"{tech.name}({cnt}dom)")
        extra = len(heavy_sundays) - 3
        s = ", ".join(names) + (f" y {extra} mas" if extra > 0 else "")
        alerts.append({
            "type": "warning", "code": "too_many_sundays",
            "msg": f"Exceso de domingos: {s}",
            "detail": "Tecnicos con 2+ domingos en el mes. Revisa la rotacion."
        })

    heavy_festivos = [(tid, cnt) for tid, cnt in tech_festivo_count.items() if cnt >= 2]
    if heavy_festivos:
        names = []
        for tid, cnt in heavy_festivos[:3]:
            tech = Technician.query.get(tid)
            if tech:
                names.append(f"{tech.name}({cnt}fest)")
        extra = len(heavy_festivos) - 3
        s = ", ".join(names) + (f" y {extra} mas" if extra > 0 else "")
        alerts.append({
            "type": "warning", "code": "too_many_festivos",
            "msg": f"Exceso de festivos: {s}",
            "detail": "Tecnicos con 2+ festivos en el mes. Revisa la rotacion."
        })

    # --- 7. Tech with sunday AND festivo too close (< 7 days apart) ---
    from collections import defaultdict as _dd
    tech_special_dates = _dd(list)
    for da in all_das:
        if da.is_sunday_holiday and da.shift == SHIFT_DOMINGO:
            tech_special_dates[da.technician_id].append(da.date)

    close_pairs = []
    for tid, dates in tech_special_dates.items():
        dates_sorted = sorted(dates)
        has_sunday = any(d.weekday() == 6 for d in dates_sorted)
        has_festivo = any(d.weekday() != 6 for d in dates_sorted)
        if has_sunday and has_festivo:
            for i in range(len(dates_sorted)-1):
                gap = (dates_sorted[i+1] - dates_sorted[i]).days
                if gap < 7:
                    tech = Technician.query.get(tid)
                    if tech:
                        close_pairs.append(f"{tech.name}({gap}d)")
                    break
    if close_pairs:
        s = ", ".join(close_pairs[:3]) + ("..." if len(close_pairs) > 3 else "")
        alerts.append({
            "type": "info", "code": "close_sunday_festivo",
            "msg": f"Domingo+festivo muy cercanos: {s}",
            "detail": "Tecnico con domingo y festivo en menos de 7 dias."
        })

        return alerts
