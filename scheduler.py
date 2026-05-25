# scheduler.py — Algoritmo inteligente de generación de horarios
# Somos Internet — Coordinación Soporte Técnico
#
# REGLAS CLAVE:
#   1. Estabilidad semanal: turno fijo toda la semana
#   2. T2 mínimo 6 técnicos diarios
#   3. Tickets: 5 técnicos T1, rotación semanal, nunca siempre los mismos
#   4. Rotación equitativa T1/T2/dominicales/tickets usando historial
#   5. Sin dominicales consecutivos para el mismo técnico
#   6. Novedades: reemplazar con mínimo impacto, usar historial para equidad

from datetime import date, timedelta
from collections import defaultdict
from models import (db, Technician, WeekSchedule, DayAssignment,
                    Novelty, TechnicianHistory, HolidayCalendar,
                    SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO,
                    NOVEDADES)

# ─── Constantes operativas ────────────────────────────────────────────────────
MIN_T2_DAILY      = 6     # mínimo técnicos T2 por día
TICKET_COUNT      = 5     # técnicos de tickets por semana (T1 exclusivo)
HOLIDAY_SHIFT     = SHIFT_DOMINGO   # turno para domingos/festivos

# Horas efectivas por turno (sin almuerzo)
HOURS_T1_WEEKDAY  = 8.0   # 7:30–16:30 menos 1h almuerzo
HOURS_T2_WEEKDAY  = 8.0   # 10:30–19:30 menos 1h almuerzo
HOURS_T1_SAT      = 5.0   # 7:30–12:30
HOURS_T2_SAT      = 7.5   # 7:30–16:00 menos 1h almuerzo
HOURS_DOM_HOL     = 7.0   # 8:00–16:00 menos 1h almuerzo


def get_week_dates(week_start: date) -> list[date]:
    """Retorna lista de 7 fechas lunes→domingo."""
    return [week_start + timedelta(days=i) for i in range(7)]


def is_holiday(d: date) -> bool:
    """Verifica si una fecha es festivo en el calendario."""
    return HolidayCalendar.query.filter_by(date=d).first() is not None


def is_sunday_or_holiday(d: date) -> bool:
    return d.weekday() == 6 or is_holiday(d)


def is_saturday(d: date) -> bool:
    return d.weekday() == 5


def get_novelty_on_date(technician_id: int, d: date) -> str | None:
    """Retorna el tipo de novedad si existe para esa fecha, o None."""
    nov = Novelty.query.filter_by(technician_id=technician_id, date=d).first()
    return nov.novelty_type if nov else None


def get_tech_history_summary(technician_id: int) -> dict:
    """Resumen acumulado de historial del técnico para algoritmo de equidad."""
    rows = TechnicianHistory.query.filter_by(
        technician_id=technician_id
    ).order_by(TechnicianHistory.week_start.desc()).all()

    if not rows:
        return {"t2_weeks": 0, "ticket_weeks": 0, "sundays": 0,
                "last_t2": None, "last_ticket": None, "last_sunday": None,
                "last_shift": None, "consecutive_sundays": 0}

    total_t2 = sum(1 for r in rows if r.shift_assigned == SHIFT_T2)
    total_tk = sum(1 for r in rows if r.was_ticket_week)
    total_sun = sum(r.sunday_count for r in rows)

    last_t2   = next((r.week_start for r in rows if r.shift_assigned == SHIFT_T2), None)
    last_tk   = next((r.week_start for r in rows if r.was_ticket_week), None)
    last_sun  = None
    consec_sun = 0

    # Detectar domingo consecutivo (última semana tuvo ≥1 domingo)
    if rows[0].sunday_count > 0:
        consec_sun = 1
        last_sun = rows[0].week_start
        if len(rows) > 1 and rows[1].sunday_count > 0:
            consec_sun = 2

    return {
        "t2_weeks":    total_t2,
        "ticket_weeks": total_tk,
        "sundays":     total_sun,
        "last_t2":     last_t2,
        "last_ticket": last_tk,
        "last_sunday": last_sun,
        "last_shift":  rows[0].shift_assigned if rows else None,
        "consecutive_sundays": consec_sun,
    }


def _tech_score_for_t2(tech: Technician, history: dict, week_start: date) -> float:
    """
    Puntuación para asignar a T2 (menor = más prioritario para rotar).
    Considera: semanas en T2, última semana en T2, turno fijo.
    """
    if tech.fixed_shift == SHIFT_T1:
        return 9999.0   # jamás a T2
    if tech.fixed_shift == SHIFT_T2:
        return -9999.0  # siempre en T2

    score = float(history["t2_weeks"]) * 10.0

    # Penalizar si ya estuvo en T2 la semana anterior
    if history["last_t2"] and (week_start - history["last_t2"]).days <= 7:
        score += 5.0

    # Penalizar si tickets_only (no pueden ir a T2)
    if tech.tickets_only:
        return 9999.0

    return score


def _tech_score_for_ticket(tech: Technician, history: dict) -> float:
    """Puntuación para asignar como técnico de tickets (menor = más prioritario)."""
    if tech.fixed_shift == SHIFT_T2:
        return 9999.0   # T2 fijos no hacen tickets
    if tech.tickets_only:
        return -9999.0  # siempre en tickets
    if tech.fixed_shift == SHIFT_T1:
        score = float(history["ticket_weeks"]) * 10.0
    else:
        score = float(history["ticket_weeks"]) * 10.0

    return score


def _tech_score_for_sunday(tech: Technician, history: dict, week_start: date) -> float:
    """Puntuación para asignar domingo/festivo (menor = más prioritario)."""
    if tech.no_sundays:
        return 9999.0

    # No permitir domingo consecutivo
    if history["consecutive_sundays"] >= 1:
        return 8888.0

    return float(history["sundays"]) * 10.0


def generate_week(week_start: date, force_regenerate: bool = False) -> dict:
    """
    Genera el horario completo para una semana.
    Retorna dict con {week_id, assignments, warnings}.
    """
    # ── 0. Validar que es lunes ───────────────────────────────────────────────
    if week_start.weekday() != 0:
        raise ValueError("week_start debe ser lunes (weekday==0)")

    week_end   = week_start + timedelta(days=6)
    week_dates = get_week_dates(week_start)

    # ── 1. Buscar/crear encabezado de semana ──────────────────────────────────
    existing = WeekSchedule.query.filter_by(week_start=week_start).first()
    if existing:
        if not force_regenerate:
            raise ValueError("Semana ya generada. Usa force_regenerate=True para regenerar.")
        # Eliminar asignaciones previas
        DayAssignment.query.filter_by(week_id=existing.id).delete()
        week_obj = existing
    else:
        week_obj = WeekSchedule(week_start=week_start, week_end=week_end)
        db.session.add(week_obj)
        db.session.flush()

    # ── 2. Cargar técnicos activos ────────────────────────────────────────────
    technicians = Technician.query.filter_by(is_active=True).all()
    if not technicians:
        raise ValueError("No hay técnicos activos registrados.")

    # ── 3. Cargar novedades de la semana ──────────────────────────────────────
    novelties_map: dict[int, dict[date, str]] = defaultdict(dict)
    week_novelties = Novelty.query.filter(
        Novelty.date >= week_start,
        Novelty.date <= week_end
    ).all()
    for nov in week_novelties:
        novelties_map[nov.technician_id][nov.date] = nov.novelty_type

    # ── 4. Cargar historial de cada técnico ───────────────────────────────────
    histories: dict[int, dict] = {}
    for tech in technicians:
        histories[tech.id] = get_tech_history_summary(tech.id)

    warnings: list[str] = []

    # ── 5. Identificar técnicos disponibles toda la semana laboral ────────────
    # "Disponible" = no tiene novedad en la mayoría de días L-V
    def available_days(tech_id: int) -> list[date]:
        return [d for d in week_dates
                if tech_id not in novelties_map or
                novelties_map[tech_id].get(d) is None]

    def is_available_weekday(tech_id: int, d: date) -> bool:
        if d.weekday() >= 5:  # sáb o dom
            return True
        return novelties_map[tech_id].get(d) is None

    # ── 6. Asignar turno semanal (T1 o T2) ───────────────────────────────────
    # Regla: mismo turno toda la semana salvo novedad
    tech_week_shift: dict[int, str] = {}

    # 6a. Técnicos con turno fijo
    for tech in technicians:
        if tech.fixed_shift in (SHIFT_T1, SHIFT_T2):
            tech_week_shift[tech.id] = tech.fixed_shift

    # 6b. Calcular cuántos T2 necesitamos asignar manualmente
    fixed_t2_count = sum(1 for t in technicians
                         if t.fixed_shift == SHIFT_T2 and t.is_active)
    needed_t2 = max(0, MIN_T2_DAILY - fixed_t2_count)

    # 6c. Técnicos sin turno fijo, ordenados por prioridad de T2
    free_techs = [t for t in technicians if t.id not in tech_week_shift]
    # tickets_only siempre van a T1
    for tech in free_techs:
        if tech.tickets_only:
            tech_week_shift[tech.id] = SHIFT_T1

    rotateable = [t for t in free_techs
                  if t.id not in tech_week_shift and not tech.tickets_only]

    # Ordenar por score para T2 (menor = más prioritario para T2)
    rotateable.sort(key=lambda t: _tech_score_for_t2(t, histories[t.id], week_start))

    # Asignar los primeros `needed_t2` al T2, el resto T1
    assigned_t2 = 0
    for tech in rotateable:
        if assigned_t2 < needed_t2 and tech.fixed_shift != SHIFT_T1:
            tech_week_shift[tech.id] = SHIFT_T2
            assigned_t2 += 1
        else:
            tech_week_shift[tech.id] = SHIFT_T1

    # Verificar cobertura T2
    total_t2 = sum(1 for v in tech_week_shift.values() if v == SHIFT_T2)
    if total_t2 < MIN_T2_DAILY:
        warnings.append(
            f"⚠️ Solo {total_t2} técnicos en T2 — mínimo requerido: {MIN_T2_DAILY}"
        )

    # ── 7. Asignar técnicos de tickets (5 de T1, rotación semanal) ────────────
    ticket_assigned: set[int] = set()
    t1_techs = [t for t in technicians
                if tech_week_shift.get(t.id) == SHIFT_T1]

    # Tickets-only primero
    for tech in t1_techs:
        if tech.tickets_only and len(ticket_assigned) < TICKET_COUNT:
            ticket_assigned.add(tech.id)

    # Completar con rotación equitativa
    if len(ticket_assigned) < TICKET_COUNT:
        t1_rotateable = [t for t in t1_techs
                         if t.id not in ticket_assigned and not t.tickets_only]
        t1_rotateable.sort(
            key=lambda t: _tech_score_for_ticket(t, histories[t.id])
        )
        for tech in t1_rotateable:
            if len(ticket_assigned) >= TICKET_COUNT:
                break
            ticket_assigned.add(tech.id)

    if len(ticket_assigned) < TICKET_COUNT:
        warnings.append(
            f"⚠️ Solo {len(ticket_assigned)} técnicos disponibles para tickets "
            f"(necesario: {TICKET_COUNT})"
        )

    # ── 8. Identificar domingos/festivos de la semana ─────────────────────────
    special_days = [d for d in week_dates if is_sunday_or_holiday(d)]
    sunday_assignments: dict[date, list[int]] = {}

    # Para cada domingo/festivo, asignar técnicos disponibles y elegibles
    for sd in special_days:
        eligible = [t for t in technicians
                    if not t.no_sundays
                    and novelties_map[t.id].get(sd) is None
                    and histories[t.id]["consecutive_sundays"] < 1]

        # Si no hay elegibles sin domingos consecutivos, abrir a todos disponibles
        if not eligible:
            eligible = [t for t in technicians
                        if not t.no_sundays
                        and novelties_map[t.id].get(sd) is None]
            if eligible:
                warnings.append(
                    f"⚠️ {sd}: no hay técnicos sin domingo consecutivo — "
                    f"se asignaron los menos recargados."
                )

        eligible.sort(key=lambda t: _tech_score_for_sunday(t, histories[t.id], week_start))

        # Asignar un técnico por domingo (ajustar a necesidad real)
        sunday_assignments[sd] = [t.id for t in eligible[:max(1, len(eligible) // 6)]]

    # ── 9. Crear DayAssignment para cada técnico x día ────────────────────────
    assignments: list[DayAssignment] = []

    for tech in technicians:
        base_shift = tech_week_shift.get(tech.id, SHIFT_T1)
        is_ticket_tech = tech.id in ticket_assigned

        for d in week_dates:
            nov_type = novelties_map[tech.id].get(d)

            # Domingo/festivo — técnico asignado a ese día
            if is_sunday_or_holiday(d):
                if nov_type:
                    shift = nov_type
                elif tech.id in sunday_assignments.get(d, []):
                    shift = HOLIDAY_SHIFT
                else:
                    shift = SHIFT_DESCANSO
                is_sh = (shift == HOLIDAY_SHIFT)
                da = DayAssignment(
                    week_id=week_obj.id,
                    technician_id=tech.id,
                    date=d,
                    shift=shift,
                    is_ticket=False,
                    is_sunday_holiday=is_sh,
                )
                assignments.append(da)
                continue

            # Día normal con novedad
            if nov_type:
                da = DayAssignment(
                    week_id=week_obj.id,
                    technician_id=tech.id,
                    date=d,
                    shift=nov_type,
                    is_ticket=False,
                    is_sunday_holiday=False,
                )
                assignments.append(da)
                continue

            # Día normal sin novedad
            da = DayAssignment(
                week_id=week_obj.id,
                technician_id=tech.id,
                date=d,
                shift=base_shift,
                is_ticket=(is_ticket_tech and d.weekday() < 5),  # solo L-V
                is_sunday_holiday=False,
            )
            assignments.append(da)

    # ── 10. Guardar en BD ─────────────────────────────────────────────────────
    for da in assignments:
        db.session.add(da)

    # ── 11. Guardar historial ─────────────────────────────────────────────────
    for tech in technicians:
        week_shift = tech_week_shift.get(tech.id, SHIFT_T1)
        was_ticket = tech.id in ticket_assigned
        sun_count  = sum(
            1 for d in week_dates
            if is_sunday_or_holiday(d)
            and tech.id in sunday_assignments.get(d, [])
            and novelties_map[tech.id].get(d) is None
        )
        had_nov = any(v for v in novelties_map[tech.id].values()
                      if v in NOVEDADES)

        prev = histories[tech.id]

        # Actualizar o crear registro de historial
        hist_row = TechnicianHistory.query.filter_by(
            technician_id=tech.id, week_start=week_start
        ).first()
        if not hist_row:
            hist_row = TechnicianHistory(
                technician_id=tech.id, week_start=week_start
            )
            db.session.add(hist_row)

        hist_row.shift_assigned    = week_shift
        hist_row.was_ticket_week   = was_ticket
        hist_row.sunday_count      = sun_count
        hist_row.had_novelty       = had_nov
        hist_row.total_t2_weeks    = prev["t2_weeks"] + (1 if week_shift == SHIFT_T2 else 0)
        hist_row.total_ticket_weeks= prev["ticket_weeks"] + (1 if was_ticket else 0)
        hist_row.total_sundays     = prev["sundays"] + sun_count

    db.session.commit()

    return {
        "week_id":   week_obj.id,
        "week_start": week_start.isoformat(),
        "week_end":   week_end.isoformat(),
        "assignments": [a.to_dict() for a in assignments],
        "warnings":  warnings,
        "t2_count":  total_t2,
        "ticket_count": len(ticket_assigned),
    }


def apply_novelty(technician_id: int, d: date, novelty_type: str,
                  notes: str = "") -> dict:
    """
    Registra una novedad y ajusta el DayAssignment existente.
    Busca reemplazo si la novedad afecta cobertura crítica (T2 < mínimo).
    """
    warnings: list[str] = []

    # Registrar novedad
    existing_nov = Novelty.query.filter_by(
        technician_id=technician_id, date=d
    ).first()
    if existing_nov:
        existing_nov.novelty_type = novelty_type
        existing_nov.notes = notes
    else:
        nov = Novelty(
            technician_id=technician_id,
            date=d,
            novelty_type=novelty_type,
            notes=notes,
        )
        db.session.add(nov)

    # Actualizar DayAssignment si existe
    da = DayAssignment.query.filter_by(
        technician_id=technician_id, date=d
    ).first()
    if da:
        prev_shift = da.shift
        da.shift = novelty_type
        da.is_ticket = False
        da.modified_at = __import__("datetime").datetime.utcnow()
        da.override_reason = f"Novedad: {novelty_type} — {notes}"

        # ── Verificar si se rompe cobertura T2 ──────────────────────────────
        if prev_shift == SHIFT_T2 and da.week_id:
            t2_remaining = DayAssignment.query.filter(
                DayAssignment.week_id == da.week_id,
                DayAssignment.date == d,
                DayAssignment.shift == SHIFT_T2,
                DayAssignment.technician_id != technician_id,
            ).count()

            if t2_remaining < MIN_T2_DAILY:
                # Buscar reemplazo para T2
                replacement = _find_t2_replacement(
                    technician_id, d, da.week_id
                )
                if replacement:
                    replacement.shift = SHIFT_T2
                    replacement.override_reason = (
                        f"Reemplazo T2 por novedad de técnico ID {technician_id}"
                    )
                    replacement.modified_at = __import__("datetime").datetime.utcnow()
                    tech_name = Technician.query.get(replacement.technician_id).name
                    warnings.append(
                        f"✅ {tech_name} asignado a T2 como reemplazo "
                        f"(cobertura mínima mantenida)."
                    )
                else:
                    warnings.append(
                        f"⚠️ T2 quedó con solo {t2_remaining} técnicos "
                        f"el {d}. No se encontró reemplazo disponible."
                    )

    db.session.commit()
    return {"success": True, "warnings": warnings}


def _find_t2_replacement(absent_tech_id: int, d: date,
                         week_id: int) -> DayAssignment | None:
    """
    Busca el mejor candidato en T1 para mover a T2 ese día,
    priorizando menor carga histórica de T2.
    """
    from sqlalchemy import or_
    # Candidatos: T1 ese día, sin novedad, sin tickets_only, sin fijo T1
    # NOTA: fixed_shift puede ser NULL — usar or_ para capturar nulos correctamente
    candidates = (
        DayAssignment.query
        .join(Technician)
        .filter(
            DayAssignment.week_id == week_id,
            DayAssignment.date == d,
            DayAssignment.shift == SHIFT_T1,
            DayAssignment.technician_id != absent_tech_id,
            or_(Technician.fixed_shift.is_(None),
                Technician.fixed_shift == SHIFT_T2),  # rotateable or forced T2 (edge case)
            Technician.tickets_only == False,
        )
        .all()
    )

    if not candidates:
        return None

    # Ordenar por menor historial de T2
    def t2_count(da: DayAssignment) -> int:
        hist = get_tech_history_summary(da.technician_id)
        return hist["t2_weeks"]

    candidates.sort(key=t2_count)
    return candidates[0]


def get_week_stats(week_id: int) -> dict:
    """Estadísticas de cobertura de una semana para el dashboard."""
    assignments = DayAssignment.query.filter_by(week_id=week_id).all()
    if not assignments:
        return {}

    from collections import Counter
    by_date: dict[str, Counter] = defaultdict(Counter)
    for a in assignments:
        by_date[a.date.isoformat()][a.shift] += 1

    t2_by_day = {d: counts.get(SHIFT_T2, 0) for d, counts in by_date.items()}
    ticket_days = {d: counts.get("T1_TICKET", 0) for d, counts in by_date.items()}

    tickets_total = sum(1 for a in assignments if a.is_ticket)