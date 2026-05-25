# app.py -- Sistema de Horarios Soporte Tecnico Somos Internet
import os
from datetime import date, datetime, timedelta
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify)
from models import (db, Technician, WeekSchedule, DayAssignment,
                    Novelty, TechnicianHistory, HolidayCalendar,
                    SHIFT_T1, SHIFT_T2, SHIFT_COLORS, NOVEDADES)
from scheduler import generate_week, apply_novelty, get_week_stats


def create_app():
    app = Flask(__name__)
    database_url = os.environ.get("DATABASE_URL", "sqlite:///turnos_soporte.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-somos-2025")
    db.init_app(app)
    with app.app_context():
        db.create_all()
        _seed_holidays()
        _seed_demo_technicians()
    return app


def _seed_holidays():
    if HolidayCalendar.query.first():
        return
    holidays = [
        (date(2025, 1, 1), "Anio Nuevo"),
        (date(2025, 1, 6), "Reyes Magos"),
        (date(2025, 3, 24), "San Jose"),
        (date(2025, 4, 17), "Jueves Santo"),
        (date(2025, 4, 18), "Viernes Santo"),
        (date(2025, 5, 1), "Dia del Trabajo"),
        (date(2025, 6, 2), "Ascension"),
        (date(2025, 6, 23), "Corpus Christi"),
        (date(2025, 6, 30), "Sagrado Corazon"),
        (date(2025, 7, 7), "San Pedro y San Pablo"),
        (date(2025, 7, 20), "Independencia"),
        (date(2025, 8, 7), "Batalla de Boyaca"),
        (date(2025, 8, 18), "Asuncion Virgen"),
        (date(2025, 10, 13), "Dia de la Raza"),
        (date(2025, 11, 3), "Todos los Santos"),
        (date(2025, 11, 17), "Independencia Cartagena"),
        (date(2025, 12, 8), "Inmaculada Concepcion"),
        (date(2025, 12, 25), "Navidad"),
        (date(2026, 1, 1), "Anio Nuevo"),
        (date(2026, 1, 12), "Reyes Magos"),
        (date(2026, 3, 23), "San Jose"),
        (date(2026, 4, 2), "Jueves Santo"),
        (date(2026, 4, 3), "Viernes Santo"),
        (date(2026, 5, 1), "Dia del Trabajo"),
        (date(2026, 5, 18), "Ascension"),
        (date(2026, 6, 8), "Corpus Christi"),
        (date(2026, 6, 15), "Sagrado Corazon"),
        (date(2026, 6, 29), "San Pedro y San Pablo"),
        (date(2026, 7, 20), "Independencia"),
        (date(2026, 8, 7), "Batalla de Boyaca"),
        (date(2026, 8, 17), "Asuncion Virgen"),
        (date(2026, 10, 12), "Dia de la Raza"),
        (date(2026, 11, 2), "Todos los Santos"),
        (date(2026, 11, 16), "Independencia Cartagena"),
        (date(2026, 12, 8), "Inmaculada Concepcion"),
        (date(2026, 12, 25), "Navidad"),
    ]
    for d, name in holidays:
        db.session.add(HolidayCalendar(date=d, name=name))
    db.session.commit()


def _seed_demo_technicians():
    if Technician.query.first():
        return
    demo = [
        {"name": "Johan Ramirez Marin",              "code": "T001"},
        {"name": "Oswaldo Andres Gaviria Puerta",     "code": "T002"},
        {"name": "Mauricio de Jesus Pulgarin",        "code": "T003"},
        {"name": "Jonathan Alberto Cardona",          "code": "T004"},
        {"name": "Julian Antonio Taborda",            "code": "T005", "fixed_shift": "T2"},
        {"name": "Camilo Becerra Chavarria",          "code": "T006"},
        {"name": "Andres Duque Durango",              "code": "T007"},
        {"name": "Juan Camilo Tabares",               "code": "T008"},
        {"name": "Hernando Hernandez",                "code": "T009"},
        {"name": "Jose David Vergara Diaz",           "code": "T010"},
        {"name": "Juan Sebastian Hoyos Osorio",       "code": "T011"},
        {"name": "Diego Leon Hinestroza Escobar",     "code": "T012"},
        {"name": "Yuber Alfredo Rodriguez Gomez",     "code": "T013"},
        {"name": "Jhon Jairo Moreno Tabares",         "code": "T014", "tickets_only": True},
        {"name": "Carlos Andres Alvarez Alzate",      "code": "T015"},
        {"name": "Valeria Restrepo Zuleta",           "code": "T016", "fixed_shift": "T2"},
        {"name": "Diego Andres Salazar Velilla",      "code": "T017"},
        {"name": "Maria Camila Gaviria",              "code": "T018"},
        {"name": "Frank Oswaldo Mena Tamayo",         "code": "T019"},
        {"name": "Cesar Leonardo Argumedo Causil",    "code": "T020"},
        {"name": "Jeison Mazo Restrepo",              "code": "T021"},
        {"name": "Santiago Corrales Parra",           "code": "T022"},
        {"name": "Carlos Esteban Sanchez Rojas",      "code": "T023", "fixed_shift": "T2"},
        {"name": "Jose Esteban Gomez Henao",          "code": "T024"},
        {"name": "Andres Gonzalez Serna",             "code": "T025"},
        {"name": "Estiven Hernandez Cano",            "code": "T026"},
        {"name": "Jonathan Alvarez Cano",             "code": "T027"},
        {"name": "Damian de Jesus Madrigal",          "code": "T028"},
        {"name": "Jhon Jairo Gil",                    "code": "T029"},
        {"name": "Nicolas Emerson Cano",              "code": "T030", "fixed_shift": "T2"},
        {"name": "Wilfran Madrid",                    "code": "T031"},
        {"name": "Didier Andres Alvarez Jimenez",     "code": "T032"},
        {"name": "Jaiver Rodriguez Ibarra",           "code": "T033"},
        {"name": "Elkin Manuel Vidal Gomez",          "code": "T034"},
        {"name": "Sebastian Ortega Agudelo",          "code": "T035"},
        {"name": "Christian Camilo Gutierrez",        "code": "T036"},
    ]
    for d in demo:
        tech = Technician(
            name=d["name"], code=d.get("code"),
            fixed_shift=d.get("fixed_shift"),
            tickets_only=d.get("tickets_only", False),
            no_sundays=d.get("no_sundays", False),
        )
        db.session.add(tech)
    db.session.commit()


app = create_app()


# --- Context processor: inyecta utilidades a todos los templates ---
@app.context_processor
def inject_globals():
    return {
        "timedelta": timedelta,
        "enumerate": enumerate,
        "now": datetime.now(),
        "min": min,
        "max": max,
    }


# --- Helpers ---
def get_current_week_start():
    today = date.today()
    return today - timedelta(days=today.weekday())


def get_week_schedule_data(week_start):
    week = WeekSchedule.query.filter_by(week_start=week_start).first()
    if not week:
        return None
    dates = [week_start + timedelta(days=i) for i in range(7)]
    technicians = (Technician.query
                   .filter_by(is_active=True)
                   .order_by(Technician.name).all())
    all_assignments = DayAssignment.query.filter_by(week_id=week.id).all()
    asgn_map = {t.id: {} for t in technicians}
    for a in all_assignments:
        asgn_map[a.technician_id][a.date] = a

    rows = []
    for tech in technicians:
        cells = []
        for d in dates:
            da = asgn_map[tech.id].get(d)
            if da:
                cells.append({
                    "shift": da.shift,
                    "color": SHIFT_COLORS.get(da.shift, "#9CA3AF"),
                    "is_ticket": da.is_ticket,
                    "is_sunday": da.is_sunday_holiday,
                    "da_id": da.id,
                })
            else:
                cells.append({"shift": "-", "color": "#E5E7EB",
                              "is_ticket": False, "is_sunday": False, "da_id": None})
        rows.append({"tech": tech, "cells": cells})

    daily_t2 = []
    daily_tickets = []
    from scheduler import is_sunday_or_holiday
    for d in dates:
        t2_count = sum(1 for a in all_assignments if a.date == d and a.shift == SHIFT_T2)
        tkt_count = sum(1 for a in all_assignments if a.date == d and a.is_ticket)
        daily_t2.append(t2_count)
        daily_tickets.append(tkt_count)

    return {
        "week": week,
        "dates": dates,
        "rows": rows,
        "daily_t2": daily_t2,
        "daily_tickets": daily_tickets,
        "shift_colors": SHIFT_COLORS,
        "is_special": [is_sunday_or_holiday(d) for d in dates],
        "min_t2": 6,
    }


# --- Rutas ---

@app.route("/")
def index():
    today = date.today()
    week_start = get_current_week_start()
    recent_weeks = (WeekSchedule.query
                    .order_by(WeekSchedule.week_start.desc()).limit(8).all())
    current_week = WeekSchedule.query.filter_by(week_start=week_start).first()
    stats = {}
    if current_week:
        stats = get_week_stats(current_week.id)
    today_novelties = Novelty.query.filter_by(date=today).all()
    total_techs = Technician.query.filter_by(is_active=True).count()
    total_t2 = Technician.query.filter_by(is_active=True, fixed_shift=SHIFT_T2).count()
    total_tickets = Technician.query.filter_by(is_active=True, tickets_only=True).count()
    return render_template("index.html",
        today=today, week_start=week_start,
        recent_weeks=recent_weeks, current_week=current_week,
        stats=stats, today_novelties=today_novelties,
        total_techs=total_techs, total_t2=total_t2, total_tickets=total_tickets,
    )


@app.route("/schedule")
@app.route("/schedule/<week_str>")
def schedule(week_str=None):
    if week_str:
        try:
            ws = datetime.strptime(week_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Fecha invalida.", "danger")
            return redirect(url_for("index"))
    else:
        ws = get_current_week_start()
    prev_week = ws - timedelta(weeks=1)
    next_week = ws + timedelta(weeks=1)
    data = get_week_schedule_data(ws)
    all_weeks = WeekSchedule.query.order_by(WeekSchedule.week_start.desc()).all()
    return render_template("schedule.html",
        week_start=ws, prev_week=prev_week,
        next_week=next_week, data=data, all_weeks=all_weeks,
    )


@app.route("/generate", methods=["GET", "POST"])
def generate():
    if request.method == "POST":
        week_str = request.form.get("week_start")
        force = request.form.get("force", "false") == "true"
        try:
            ws = datetime.strptime(week_str, "%Y-%m-%d").date()
            ws = ws - timedelta(days=ws.weekday())
            result = generate_week(ws, force_regenerate=force)
            for w in result.get("warnings", []):
                flash(w, "warning")
            flash(f"Semana {ws} generada: {result['t2_count']} T2 | {result['ticket_count']} Tickets.", "success")
            return redirect(url_for("schedule", week_str=ws.isoformat()))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    return render_template("generate.html", next_monday=next_monday)


@app.route("/novelties", methods=["GET", "POST"])
def novelties():
    if request.method == "POST":
        tech_id = int(request.form.get("technician_id"))
        date_str = request.form.get("date")
        novelty_type = request.form.get("novelty_type")
        notes = request.form.get("notes", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            result = apply_novelty(tech_id, d, novelty_type, notes)
            for w in result.get("warnings", []):
                flash(w, "warning")
            flash("Novedad registrada y horario actualizado.", "success")
        except Exception as e:
            flash(f"Error: {e}", "danger")
        return redirect(url_for("novelties"))
    today = date.today()
    week_start = get_current_week_start()
    week_novelties = (Novelty.query
                      .filter(Novelty.date >= week_start,
                              Novelty.date <= week_start + timedelta(days=6))
                      .order_by(Novelty.date, Novelty.technician_id).all())
    technicians = (Technician.query.filter_by(is_active=True)
                   .order_by(Technician.name).all())
    return render_template("novelties.html",
        today=today, week_start=week_start,
        week_novelties=week_novelties, technicians=technicians,
        novelty_types=NOVEDADES, shift_colors=SHIFT_COLORS,
    )


@app.route("/novelty/delete/<int:nov_id>", methods=["POST"])
def delete_novelty(nov_id):
    nov = db.session.get(Novelty, nov_id)
    if not nov:
        flash("Novedad no encontrada.", "danger")
        return redirect(url_for("novelties"))
    db.session.delete(nov)
    db.session.commit()
    flash("Novedad eliminada.", "success")
    return redirect(url_for("novelties"))


@app.route("/technicians")
def technicians():
    techs = Technician.query.order_by(Technician.name).all()
    for tech in techs:
        hist = (TechnicianHistory.query
                .filter_by(technician_id=tech.id)
                .order_by(TechnicianHistory.week_start.desc()).first())
        tech._last_hist = hist
    return render_template("technicians.html", technicians=techs,
                           shift_colors=SHIFT_COLORS)


@app.route("/technicians/add", methods=["POST"])
def add_technician():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip() or None
    supervisor = request.form.get("supervisor", "").strip() or None
    fixed_shift = request.form.get("fixed_shift") or None
    tickets_only = request.form.get("tickets_only") == "on"
    no_sundays = request.form.get("no_sundays") == "on"
    if not name:
        flash("El nombre es obligatorio.", "danger")
        return redirect(url_for("technicians"))
    tech = Technician(name=name, code=code, supervisor=supervisor,
                      fixed_shift=fixed_shift, tickets_only=tickets_only,
                      no_sundays=no_sundays)
    db.session.add(tech)
    db.session.commit()
    flash(f"Tecnico {name} agregado.", "success")
    return redirect(url_for("technicians"))


@app.route("/technicians/edit/<int:tech_id>", methods=["POST"])
def edit_technician(tech_id):
    tech = db.session.get(Technician, tech_id)
    if not tech:
        flash("Tecnico no encontrado.", "danger")
        return redirect(url_for("technicians"))
    tech.name = request.form.get("name", tech.name).strip()
    tech.code = request.form.get("code", "").strip() or tech.code
    tech.supervisor = request.form.get("supervisor", "").strip() or None
    tech.fixed_shift = request.form.get("fixed_shift") or None
    tech.tickets_only = request.form.get("tickets_only") == "on"
    tech.no_sundays = request.form.get("no_sundays") == "on"
    tech.is_active = request.form.get("is_active") == "on"
    db.session.commit()
    flash(f"{tech.name} actualizado.", "success")
    return redirect(url_for("technicians"))


@app.route("/history")
def history():
    technicians = (Technician.query.filter_by(is_active=True)
                   .order_by(Technician.name).all())
    rows = (TechnicianHistory.query
            .order_by(TechnicianHistory.week_start.desc())
            .limit(12 * max(len(technicians), 1)).all())
    hist_by_tech = {t.id: [] for t in technicians}
    for r in rows:
        if r.technician_id in hist_by_tech:
            hist_by_tech[r.technician_id].append(r)
    return render_template("history.html",
        technicians=technicians, hist_by_tech=hist_by_tech,
        shift_colors=SHIFT_COLORS)


# --- API JSON ---
@app.route("/api/week/<week_str>")
def api_week(week_str):
    try:
        ws = datetime.strptime(week_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato invalido. Use YYYY-MM-DD"}), 400
    week = WeekSchedule.query.filter_by(week_start=ws).first()
    if not week:
        return jsonify({"error": "Semana no generada"}), 404
    return jsonify({
        "week_start": ws.isoformat(),
        "week_end": week.week_end.isoformat(),
        "assignments": [a.to_dict() for a in week.days],
    })


@app.route("/api/technicians")
def api_technicians():
    techs = Technician.query.filter_by(is_active=True).all()
    return jsonify([t.to_dict() for t in techs])


@app.route("/api/novelties/<date_str>")
def api_novelties(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Formato invalido"}), 400
    return jsonify([n.to_dict() for n in Novelty.query.filter_by(date=d).all()])


# --- Template filters ---
@app.template_filter("weekday_es")
def weekday_es(d):
    DAYS = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
    return DAYS[d.weekday()]


@app.template_filter("date_fmt")
def date_fmt(d):
    return d.strftime("%d/%m")


# --- Entry point ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port,
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
