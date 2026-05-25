# scheduler.py -- Algoritmo de generacion de horarios v2
# Soporta forzado manual de T2 y tickets antes de generar
from datetime import date, timedelta
from collections import defaultdict
from models import (db, Technician, WeekSchedule, DayAssignment,
                    Novelty, TechnicianHistory, HolidayCalendar, Config,
                    SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO, NOVEDADES)

DEFAULT_MIN_T2 = 6
DEFAULT_TICKET_COUNT = 5
HOLIDAY_SHIFT = SHIFT_DOMINGO


def get_config_int(key, default):
    val = Config.get(key)
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def get_week_dates(week_start):
    return [week_start + timedelta(days=i) for i in range(7)]


def is_holiday(d):
    return HolidayCalendar.query.filter_by(date=d).first() is not None


def is_sunday_or_holiday(d):
    return d.weekday() == 6 or is_holiday(d)


def get_tech_history_summary(tech_id):
    rows = (TechnicianHistory.query
            .filter_by(technician_id=tech_id)
            .order_by(TechnicianHistory.week_start.desc()).all())
    if not rows:
        return {"t2_weeks": 0, "ticket_weeks": 0, "sundays": 0,
                "last_t2": None, "last_ticket": None,
                "last_shift": None, "consecutive_sundays": 0}
    total_t2 = sum(1 for r in rows if r.shift_assigned == SHIFT_T2)
    total_tk = sum(1 for r in rows if r.was_ticket_week)
    total_sun = sum(r.sunday_count for r in rows)
    consec_sun = 0
    if rows[0].sunday_count > 0:
        consec_sun = 1
        if len(rows) > 1 and rows[1].sunday_count > 0:
            consec_sun = 2
    return {"t2_weeks": total_t2, "ticket_weeks": total_tk, "sundays": total_sun,
            "last_t2": next((r.week_start for r in rows if r.shift_assigned == SHIFT_T2), None),
            "last_ticket": next((r.week_start for r in rows if r.was_ticket_week), None),
            "last_shift": rows[0].shift_assigned,
            "consecutive_sundays": consec_sun}


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


def _sunday_score(tech, history):
    if tech.no_sundays:
        return 9999.0
    if history["consecutive_sundays"] >= 1:
        return 8888.0
    return float(history["sundays"]) * 10.0


def generate_week(week_start, force_regenerate=False,
                  forced_t2_ids=None, forced_ticket_ids=None):
    """
    Genera el horario de una semana.
    forced_t2_ids: lista de IDs a forzar en T2 (override manual)
    forced_ticket_ids: lista de IDs a forzar como tickets (override manual)
    """
    if week_start.weekday() != 0:
        raise ValueError("week_start debe ser lunes")

    MIN_T2      = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
    TICKET_COUNT= get_config_int("TICKET_COUNT", DEFAULT_TICKET_COUNT)
    week_end    = week_start + timedelta(days=6)
    week_dates  = get_week_dates(week_start)

    existing = WeekSchedule.query.filter_by(week_start=week_start).first()
    if existing:
        if not force_regenerate:
            raise ValueError("Semana ya generada. Activa 'forzar regeneracion'.")
        if existing.is_locked:
            raise ValueError("Semana bloqueada. Desbloquea antes de regenerar.")
        DayAssignment.query.filter_by(week_id=existing.id).delete()
        week_obj = existing
        week_obj.generated_at = __import__("datetime").datetime.utcnow()
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
        Novelty.date_end >= week_start
    ).all()
    for nov in week_novelties:
        d = nov.date_start
        while d <= nov.date_end and d <= week_end:
            if d >= week_start:
                novelties_map[nov.technician_id][d] = nov.novelty_type
            d += timedelta(days=1)

    histories = {t.id: get_tech_history_summary(t.id) for t in technicians}
    warnings = []

    # --- Asignar turnos semanales ---
    tech_week_shift = {}

    # Fijos primero
    for tech in technicians:
        if tech.fixed_shift in (SHIFT_T1, SHIFT_T2):
            tech_week_shift[tech.id] = tech.fixed_shift

    # Forzados manualmente (override del usuario)
    if forced_t2_ids:
        for tid in forced_t2_ids:
            tech_week_shift[tid] = SHIFT_T2

    # tickets_only siempre T1
    for tech in technicians:
        if tech.tickets_only and tech.id not in tech_week_shift:
            tech_week_shift[tech.id] = SHIFT_T1

    # Rotacion automatica para los restantes
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
        # Tickets only primero
        for t in t1_techs:
            if t.tickets_only and t.id not in ticket_assigned and len(ticket_assigned) < TICKET_COUNT:
                ticket_assigned.add(t.id)
        # Rotacion
        rotateable = [t for t in t1_techs if not t.tickets_only and t.id not in ticket_assigned]
        rotateable.sort(key=lambda t: _ticket_score(t, histories[t.id]))
        for t in rotateable:
            if len(ticket_assigned) >= TICKET_COUNT:
                break
            ticket_assigned.add(t.id)

    # --- Dominicales ---
    special_days = [d for d in week_dates if is_sunday_or_holiday(d)]
    sunday_assignments = {}
    for sd in special_days:
        eligible = [t for t in technicians
                    if not t.no_sundays and novelties_map[t.id].get(sd) is None
                    and histories[t.id]["consecutive_sundays"] < 1]
        if not eligible:
            eligible = [t for t in technicians
                        if not t.no_sundays and novelties_map[t.id].get(sd) is None]
            if eligible:
                warnings.append(f"{sd}: sin candidatos sin domingo consecutivo")
        eligible.sort(key=lambda t: _sunday_score(t, histories[t.id]))
        # Asignar 1 por dominical minimo (operacion soporte = 1 guardia dominical)
        count = max(1, len(eligible) // 8)
        sunday_assignments[sd] = [t.id for t in eligible[:count]]

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
                da = DayAssignment(week_id=week_obj.id, technician_id=tech.id,
                                   date=d, shift=base_shift,
                                   is_ticket=(is_ticket_tech and d.weekday() < 5))
            assignments.append(da)

    for da in assignments:
        db.session.add(da)

    # --- Historial ---
    for tech in technicians:
        w_shift = tech_week_shift.get(tech.id, SHIFT_T1)
        was_tk  = tech.id in ticket_assigned
        sun_cnt = sum(1 for d in week_dates
                      if is_sunday_or_holiday(d)
                      and tech.id in sunday_assignments.get(d, [])
                      and novelties_map[tech.id].get(d) is None)
        had_nov = any(novelties_map[tech.id].values())
        prev = histories[tech.id]

        hist = TechnicianHistory.query.filter_by(
            technician_id=tech.id, week_start=week_start).first()
        if not hist:
            hist = TechnicianHistory(technician_id=tech.id, week_start=week_start)
            db.session.add(hist)
        hist.shift_assigned     = w_shift
        hist.was_ticket_week    = was_tk
        hist.sunday_count       = sun_cnt
        hist.had_novelty        = had_nov
        hist.total_t2_weeks     = prev["t2_weeks"] + (1 if w_shift == SHIFT_T2 else 0)
        hist.total_ticket_weeks = prev["ticket_weeks"] + (1 if was_tk else 0)
        hist.total_sundays      = prev["sundays"] + sun_cnt

    db.session.commit()
    return {"week_id": week_obj.id, "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "assignments": [a.to_dict() for a in assignments],
            "warnings": warnings, "t2_count": total_t2,
            "ticket_count": len(ticket_assigned)}


def apply_novelty_range(technician_id, date_start, date_end, novelty_type, notes=""):
    """Registra novedad por rango de fechas y actualiza asignaciones existentes."""
    from sqlalchemy import or_
    warnings = []

    # Eliminar novedad existente que se solape
    existing = Novelty.query.filter(
        Novelty.technician_id == technician_id,
        Novelty.date_start <= date_end,
        Novelty.date_end >= date_start
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
            da.modified_at = __import__("datetime").datetime.utcnow()
            # Verificar cobertura T2
            if old == SHIFT_T2:
                t2_left = DayAssignment.query.filter(
                    DayAssignment.week_id == da.week_id,
                    DayAssignment.date == d,
                    DayAssignment.shift == SHIFT_T2,
                    DayAssignment.technician_id != technician_id
                ).count()
                min_t2 = get_config_int("MIN_T2_DAILY", DEFAULT_MIN_T2)
                if t2_left < min_t2:
                    warnings.append(f"T2 bajo minimo el {d} ({t2_left}/{min_t2})")
        d += timedelta(days=1)

    db.session.commit()
    return {"success": True, "warnings": warnings}


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
    return {"t2_by_day": t2_by_day,
            "min_t2": min(t2_by_day.values()) if t2_by_day else 0,
            "tickets_total": sum(1 for a in assignments if a.is_ticket),
            "total_assignments": len(assignments),
            "min_t2_config": min_t2}
