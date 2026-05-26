# app.py -- Flask scheduling app v2
import os
import calendar as cal_module
from datetime import date, timedelta, datetime
from flask import (Flask, render_template, request, redirect,
                   url_for, jsonify, flash)
from models import (db, Technician, WeekSchedule, DayAssignment, Novelty,
                    TechnicianHistory, HolidayCalendar, Config, AuditLog,
                    SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO,
                    ALL_SHIFTS, SHIFT_LABELS, SHIFT_COLORS, NOVEDADES)
from scheduler import (generate_week, apply_novelty_range,
                       get_week_stats, is_sunday_or_holiday)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-en-produccion-2024")

DB_PATH = os.environ.get("DB_PATH", "turnos.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


# ---------------------------------------------------------------
# CONTEXT PROCESSOR
# ---------------------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        "timedelta": timedelta,
        "enumerate": enumerate,
        "now": datetime.utcnow(),
        "min": min,
        "max": max,
        "date": date,
        "SHIFT_COLORS": SHIFT_COLORS,
        "SHIFT_LABELS": SHIFT_LABELS,
    }


# ---------------------------------------------------------------
# JINJA FILTERS
# ---------------------------------------------------------------
def date_fmt(d):
    if not d:
        return ""
    return d.strftime("%d/%m/%Y")


def weekday_es(d):
    days = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    return days[d.weekday()]


app.jinja_env.filters["date_fmt"] = date_fmt
app.jinja_env.filters["weekday_es"] = weekday_es


# ---------------------------------------------------------------
# DB INIT + CONFIG SEED
# ---------------------------------------------------------------
def seed_config():
    defaults = [
        ("MIN_T2_DAILY",  "6",  "Minimo tecnicos T2 por dia"),
        ("TICKET_COUNT",  "5",  "Tecnicos ticket por semana"),
    ]
    changed = False
    for key, val, label in defaults:
        if Config.query.filter_by(key=key).first() is None:
            db.session.add(Config(key=key, value=val, label=label))
            changed = True
    if changed:
        db.session.commit()


with app.app_context():
    db.create_all()
    seed_config()


# ---------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------
@app.route("/")
def index():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week = WeekSchedule.query.filter_by(week_start=monday).first()

    total_techs     = Technician.query.filter_by(is_active=True).count()
    total_weeks     = WeekSchedule.query.count()
    active_novelties = Novelty.query.filter(Novelty.date_end >= today).count()

    t2_today = 0
    if week:
        t2_today = DayAssignment.query.filter_by(
            week_id=week.id, date=today, shift=SHIFT_T2
        ).count()

    min_t2 = int(Config.get("MIN_T2_DAILY", "6"))

    recent_weeks = (WeekSchedule.query
                    .order_by(WeekSchedule.week_start.desc())
                    .limit(6).all())

    recent_audit = (AuditLog.query
                    .order_by(AuditLog.timestamp.desc())
                    .limit(10).all())

    # T2 per day this week for mini chart
    chart_labels = []
    chart_t2 = []
    if week:
        for i in range(7):
            d = monday + timedelta(days=i)
            cnt = DayAssignment.query.filter_by(
                week_id=week.id, date=d, shift=SHIFT_T2
            ).count()
            chart_labels.append(weekday_es(d))
            chart_t2.append(cnt)

    return render_template("index.html",
        today=today, week=week, monday=monday,
        total_techs=total_techs, total_weeks=total_weeks,
        active_novelties=active_novelties,
        t2_today=t2_today, min_t2=min_t2,
        recent_weeks=recent_weeks, recent_audit=recent_audit,
        chart_labels=chart_labels, chart_t2=chart_t2)


# ---------------------------------------------------------------
# SCHEDULE (weekly grid)
# ---------------------------------------------------------------
@app.route("/schedule")
@app.route("/schedule/<week_str>")
def schedule(week_str=None):
    today = date.today()
    if week_str:
        try:
            week_start = date.fromisoformat(week_str)
        except ValueError:
            week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=today.weekday())

    week = WeekSchedule.query.filter_by(week_start=week_start).first()
    all_weeks = WeekSchedule.query.order_by(WeekSchedule.week_start.desc()).all()

    data = None
    if week:
        week_dates = [week_start + timedelta(days=i) for i in range(7)]
        technicians = (Technician.query
                       .filter_by(is_active=True)
                       .order_by(Technician.name).all())

        daily_t2      = [0] * 7
        daily_tickets = [0] * 7
        rows = []

        for tech in technicians:
            cells = []
            for i, d in enumerate(week_dates):
                da = DayAssignment.query.filter_by(
                    week_id=week.id, technician_id=tech.id, date=d
                ).first()
                if da:
                    cell = da.to_dict()
                    if da.shift == SHIFT_T2:
                        daily_t2[i] += 1
                    if da.is_ticket and d.weekday() < 5:
                        daily_tickets[i] += 1
                else:
                    cell = {
                        "id": None,
                        "shift": "--",
                        "is_ticket": False,
                        "color": "#9CA3AF",
                        "label": "Sin asignar",
                        "is_sunday_holiday": False,
                        "is_manual": False,
                        "technician_id": tech.id,
                        "date": d.isoformat(),
                    }
                cells.append(cell)
            rows.append({"tech": tech, "cells": cells})

        is_special = [is_sunday_or_holiday(d) for d in week_dates]
        min_t2_val = min(daily_t2) if daily_t2 else 0

        data = {
            "week": week,
            "dates": week_dates,
            "rows": rows,
            "daily_t2": daily_t2,
            "daily_tickets": daily_tickets,
            "is_special": is_special,
            "min_t2": min_t2_val,
        }

    prev_week = week_start - timedelta(days=7)
    next_week = week_start + timedelta(days=7)
    min_t2_cfg = int(Config.get("MIN_T2_DAILY", "6"))

    return render_template("schedule.html",
        week_start=week_start, week=week, data=data,
        all_weeks=all_weeks, prev_week=prev_week, next_week=next_week,
        all_shifts=ALL_SHIFTS, shift_labels=SHIFT_LABELS,
        shift_colors=SHIFT_COLORS, min_t2_cfg=min_t2_cfg)


# ---------------------------------------------------------------
# GENERATE
# ---------------------------------------------------------------
@app.route("/generate", methods=["GET", "POST"])
def generate():
    technicians = (Technician.query
                   .filter_by(is_active=True)
                   .order_by(Technician.name).all())
    min_t2      = int(Config.get("MIN_T2_DAILY", "6"))
    ticket_count = int(Config.get("TICKET_COUNT", "5"))

    if request.method == "POST":
        week_str    = request.form.get("week_start")
        force       = request.form.get("force_regenerate") == "on"
        forced_t2   = [int(x) for x in request.form.getlist("forced_t2_ids") if x]
        forced_tk   = [int(x) for x in request.form.getlist("forced_ticket_ids") if x]

        try:
            ws = date.fromisoformat(week_str)
            result = generate_week(
                ws,
                force_regenerate=force,
                forced_t2_ids=forced_t2 or None,
                forced_ticket_ids=forced_tk or None,
            )

            AuditLog.log("week", result["week_id"], "generate",
                         f"Semana {ws} generada. T2={result['t2_count']}, "
                         f"Tickets={result['ticket_count']}")
            db.session.commit()

            for w in result.get("warnings", []):
                flash(f"Aviso: {w}", "warning")
            flash(f"Semana generada. T2: {result['t2_count']}, "
                  f"Tickets: {result['ticket_count']}", "success")
            return redirect(url_for("schedule", week_str=ws.isoformat()))
        except ValueError as e:
            flash(str(e), "danger")

    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    return render_template("generate.html",
        technicians=technicians, today=today, monday=monday,
        min_t2=min_t2, ticket_count=ticket_count)


# ---------------------------------------------------------------
# NOVELTIES
# ---------------------------------------------------------------
@app.route("/novelties", methods=["GET", "POST"])
def novelties():
    today  = date.today()
    monday = today - timedelta(days=today.weekday())

    week_str = request.args.get("week_start")
    try:
        week_start = date.fromisoformat(week_str) if week_str else monday
    except ValueError:
        week_start = monday
    week_end = week_start + timedelta(days=6)

    technicians = (Technician.query
                   .filter_by(is_active=True)
                   .order_by(Technician.name).all())

    if request.method == "POST":
        tech_id       = int(request.form["technician_id"])
        date_start_s  = request.form.get("date_start") or request.form.get("date")
        date_end_s    = request.form.get("date_end") or date_start_s
        nov_type      = request.form["novelty_type"]
        notes         = request.form.get("notes", "")

        try:
            d_start = date.fromisoformat(date_start_s)
            d_end   = date.fromisoformat(date_end_s)
            if d_end < d_start:
                d_end = d_start

            result = apply_novelty_range(tech_id, d_start, d_end, nov_type, notes)

            tech = Technician.query.get(tech_id)
            AuditLog.log("novelty", tech_id, "create",
                         f"{tech.name}: {nov_type} {d_start} al {d_end}")
            db.session.commit()

            for w in result.get("warnings", []):
                flash(f"Aviso: {w}", "warning")
            flash("Novedad registrada.", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("novelties",
                                week_start=week_start.isoformat()))

    week_novelties = (Novelty.query
                      .filter(Novelty.date_start <= week_end,
                              Novelty.date_end >= week_start)
                      .order_by(Novelty.date_start).all())

    active_novelties = (Novelty.query
                        .filter(Novelty.date_end >= today)
                        .order_by(Novelty.date_start).all())

    return render_template("novelties.html",
        today=today, week_start=week_start, week_end=week_end,
        technicians=technicians,
        week_novelties=week_novelties,
        active_novelties=active_novelties,
        novedades_types=NOVEDADES,
        SHIFT_COLORS=SHIFT_COLORS, SHIFT_LABELS=SHIFT_LABELS)


@app.route("/novelties/<int:nov_id>/delete", methods=["POST"])
def delete_novelty(nov_id):
    nov = Novelty.query.get_or_404(nov_id)
    tech_name = nov.technician.name if nov.technician else "?"
    AuditLog.log("novelty", nov_id, "delete",
                 f"Eliminada {nov.novelty_type} de {tech_name}")
    db.session.delete(nov)
    db.session.commit()
    flash("Novedad eliminada.", "success")
    return redirect(request.referrer or url_for("novelties"))


# ---------------------------------------------------------------
# API -- inline cell editing
# ---------------------------------------------------------------
@app.route("/api/assignment/<int:da_id>/shift", methods=["PATCH"])
def api_update_shift(da_id):
    da   = DayAssignment.query.get_or_404(da_id)
    week = WeekSchedule.query.get(da.week_id)
    if week and week.is_locked:
        return jsonify({"error": "Semana bloqueada"}), 403

    body      = request.get_json(force=True)
    new_shift = body.get("shift", "").upper()
    if not new_shift or new_shift not in ALL_SHIFTS:
        return jsonify({"error": f"Turno invalido: {new_shift}"}), 400

    old_shift    = da.shift
    da.shift     = new_shift
    da.is_manual = True
    da.override_reason = body.get("reason", "Edicion manual")
    da.modified_at     = datetime.utcnow()
    if new_shift not in (SHIFT_T1,):
        da.is_ticket = False

    AuditLog.log("assignment", da_id, "update",
                 f"Turno: {old_shift} -> {new_shift}",
                 field="shift", old=old_shift, new=new_shift)
    db.session.commit()
    return jsonify(da.to_dict())


@app.route("/api/assignment/<int:da_id>/ticket", methods=["PATCH"])
def api_toggle_ticket(da_id):
    da   = DayAssignment.query.get_or_404(da_id)
    week = WeekSchedule.query.get(da.week_id)
    if week and week.is_locked:
        return jsonify({"error": "Semana bloqueada"}), 403

    da.is_ticket   = not da.is_ticket
    da.is_manual   = True
    da.modified_at = datetime.utcnow()
    AuditLog.log("assignment", da_id, "update",
                 f"Ticket: {da.is_ticket}", field="is_ticket")
    db.session.commit()
    return jsonify(da.to_dict())


# ---------------------------------------------------------------
# LOCK / UNLOCK week
# ---------------------------------------------------------------
@app.route("/week/<int:week_id>/lock", methods=["POST"])
def lock_week(week_id):
    week = WeekSchedule.query.get_or_404(week_id)
    week.is_locked = True
    AuditLog.log("week", week_id, "lock", f"Semana {week.week_start} bloqueada")
    db.session.commit()
    flash("Semana bloqueada.", "info")
    return redirect(url_for("schedule", week_str=week.week_start.isoformat()))


@app.route("/week/<int:week_id>/unlock", methods=["POST"])
def unlock_week(week_id):
    week = WeekSchedule.query.get_or_404(week_id)
    week.is_locked = False
    AuditLog.log("week", week_id, "unlock", f"Semana {week.week_start} desbloqueada")
    db.session.commit()
    flash("Semana desbloqueada.", "info")
    return redirect(url_for("schedule", week_str=week.week_start.isoformat()))


# ---------------------------------------------------------------
# MONTHLY VIEW
# ---------------------------------------------------------------
@app.route("/month")
@app.route("/month/<int:year>/<int:month>")
def month_view(year=None, month=None):
    today = date.today()
    if not year:
        year = today.year
    if not month:
        month = today.month

    _, days_in_month = cal_module.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, days_in_month)

    weeks = (WeekSchedule.query
             .filter(WeekSchedule.week_start <= month_end,
                     WeekSchedule.week_end   >= month_start)
             .order_by(WeekSchedule.week_start).all())

    min_t2 = int(Config.get("MIN_T2_DAILY", "6"))

    days_data = {}
    for offset in range(days_in_month):
        d = month_start + timedelta(days=offset)
        t2_cnt = 0
        for wk in weeks:
            t2_cnt += DayAssignment.query.filter_by(
                week_id=wk.id, date=d, shift=SHIFT_T2
            ).count()
        days_data[d] = {
            "t2": t2_cnt,
            "is_special": is_sunday_or_holiday(d),
            "has_week": any(wk.week_start <= d <= wk.week_end for wk in weeks),
        }

    # prev / next month navigation
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    month_names = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                   "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

    # Calendar grid: week-rows (Mon-Sun)
    first_dow = month_start.weekday()  # 0=Mon
    grid = []
    week_row = [None] * first_dow
    for offset in range(days_in_month):
        d = month_start + timedelta(days=offset)
        week_row.append(d)
        if len(week_row) == 7:
            grid.append(week_row)
            week_row = []
    if week_row:
        while len(week_row) < 7:
            week_row.append(None)
        grid.append(week_row)

    return render_template("month.html",
        year=year, month=month,
        month_start=month_start, month_end=month_end,
        days_in_month=days_in_month, days_data=days_data,
        weeks=weeks, min_t2=min_t2, today=today,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        month_name=month_names[month - 1],
        grid=grid)


# ---------------------------------------------------------------
# TECHNICIANS
# ---------------------------------------------------------------
@app.route("/technicians")
def technicians():
    all_techs = (Technician.query
                 .order_by(Technician.is_active.desc(), Technician.name)
                 .all())
    return render_template("technicians.html", technicians=all_techs,
                           all_shifts=[SHIFT_T1, SHIFT_T2])


@app.route("/technicians/add", methods=["GET", "POST"])
def add_technician():
    if request.method == "GET":
        return redirect(url_for("technicians"))
    name        = request.form.get("name", "").strip()
    code        = request.form.get("code", "").strip() or None
    supervisor  = request.form.get("supervisor", "").strip() or None
    fixed_shift = request.form.get("fixed_shift") or None
    tickets_only = request.form.get("tickets_only") == "on"
    no_sundays   = request.form.get("no_sundays") == "on"

    if not name:
        flash("El nombre es requerido.", "danger")
        return redirect(url_for("technicians"))

    tech = Technician(name=name, code=code, supervisor=supervisor,
                      fixed_shift=fixed_shift,
                      tickets_only=tickets_only,
                      no_sundays=no_sundays)
    db.session.add(tech)
    AuditLog.log("technician", None, "create", f"Tecnico creado: {name}")
    db.session.commit()
    flash(f"Tecnico '{name}' agregado.", "success")
    return redirect(url_for("technicians"))


@app.route("/technicians/<int:tech_id>/toggle", methods=["POST"])
def toggle_technician(tech_id):
    tech = Technician.query.get_or_404(tech_id)
    tech.is_active = not tech.is_active
    action = "activated" if tech.is_active else "deactivated"
    AuditLog.log("technician", tech_id, action,
                 f"{tech.name}: activo={tech.is_active}")
    db.session.commit()
    flash(f"{tech.name}: {'activo' if tech.is_active else 'inactivo'}.", "info")
    return redirect(url_for("technicians"))


@app.route("/technicians/<int:tech_id>/edit", methods=["POST"])
def edit_technician(tech_id):
    tech = Technician.query.get_or_404(tech_id)
    tech.name        = request.form.get("name", tech.name).strip()
    tech.supervisor  = request.form.get("supervisor", "").strip() or None
    tech.fixed_shift = request.form.get("fixed_shift") or None
    tech.tickets_only = request.form.get("tickets_only") == "on"
    tech.no_sundays   = request.form.get("no_sundays") == "on"
    AuditLog.log("technician", tech_id, "update", f"Editado: {tech.name}")
    db.session.commit()
    flash(f"Tecnico '{tech.name}' actualizado.", "success")
    return redirect(url_for("technicians"))


# ---------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------
@app.route("/config", methods=["GET", "POST"])
def config_view():
    if request.method == "POST":
        try:
            min_t2_val = request.form.get("min_t2")
            tk_val     = request.form.get("ticket_count")
            if min_t2_val:
                Config.set("MIN_T2_DAILY", int(min_t2_val),
                           "Minimo tecnicos T2 por dia")
                AuditLog.log("config", None, "update",
                             f"MIN_T2_DAILY={min_t2_val}")
            if tk_val:
                Config.set("TICKET_COUNT", int(tk_val),
                           "Tecnicos ticket por semana")
                AuditLog.log("config", None, "update",
                             f"TICKET_COUNT={tk_val}")
            db.session.commit()
            flash("Configuracion guardada.", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")
        return redirect(url_for("config_view"))

    configs = Config.query.all()
    return render_template("config.html", configs=configs)


# ---------------------------------------------------------------
# HOLIDAYS
# ---------------------------------------------------------------
@app.route("/holidays", methods=["GET", "POST"])
def holidays():
    if request.method == "POST":
        date_str = request.form.get("date")
        name     = request.form.get("name", "Festivo").strip()
        try:
            d = date.fromisoformat(date_str)
            if not HolidayCalendar.query.filter_by(date=d).first():
                db.session.add(HolidayCalendar(date=d, name=name))
                db.session.commit()
                flash(f"Festivo agregado: {d} - {name}", "success")
            else:
                flash("Esa fecha ya existe.", "warning")
        except Exception as e:
            flash(f"Error: {e}", "danger")
        return redirect(url_for("holidays"))

    all_holidays = (HolidayCalendar.query
                    .order_by(HolidayCalendar.date).all())
    return render_template("holidays.html", holidays=all_holidays)


@app.route("/holidays/<int:hol_id>/delete", methods=["POST"])
def delete_holiday(hol_id):
    h = HolidayCalendar.query.get_or_404(hol_id)
    db.session.delete(h)
    db.session.commit()
    flash("Festivo eliminado.", "success")
    return redirect(url_for("holidays"))


# ---------------------------------------------------------------
# ADMIN
# ---------------------------------------------------------------
@app.route("/admin")
def admin():
    total_techs      = Technician.query.filter_by(is_active=True).count()
    inactive_techs   = Technician.query.filter_by(is_active=False).count()
    total_weeks      = WeekSchedule.query.count()
    locked_weeks     = WeekSchedule.query.filter_by(is_locked=True).count()
    total_novelties  = Novelty.query.count()
    total_holidays   = HolidayCalendar.query.count()
    configs          = Config.query.all()
    recent_audit     = (AuditLog.query
                        .order_by(AuditLog.timestamp.desc())
                        .limit(20).all())

    return render_template("admin.html",
        total_techs=total_techs, inactive_techs=inactive_techs,
        total_weeks=total_weeks, locked_weeks=locked_weeks,
        total_novelties=total_novelties, total_holidays=total_holidays,
        configs=configs, recent_audit=recent_audit)


# ---------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------
@app.route("/audit")
def audit():
    page    = request.args.get("page", 1, type=int)
    per_page = 50
    logs = (AuditLog.query
            .order_by(AuditLog.timestamp.desc())
            .paginate(page=page, per_page=per_page, error_out=False))
    return render_template("audit.html", logs=logs)


# ---------------------------------------------------------------
# HISTORY / EQUITY
# ---------------------------------------------------------------
@app.route("/history")
def history():
    technicians = (Technician.query
                   .filter_by(is_active=True)
                   .order_by(Technician.name).all())
    hist_data = []
    for tech in technicians:
        rows = (TechnicianHistory.query
                .filter_by(technician_id=tech.id)
                .order_by(TechnicianHistory.week_start.desc())
                .limit(8).all())
        latest = rows[0] if rows else None
        hist_data.append({
            "tech":         tech,
            "total_t2":     latest.total_t2_weeks    if latest else 0,
            "total_tickets": latest.total_ticket_weeks if latest else 0,
            "total_sundays": latest.total_sundays      if latest else 0,
            "last_week":    latest.week_start          if latest else None,
            "rows":         rows,
        })
    hist_data.sort(key=lambda x: x["total_t2"], reverse=True)
    return render_template("history.html", hist_data=hist_data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
