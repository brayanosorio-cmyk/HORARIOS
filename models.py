# models.py — Modelos de base de datos para Sistema de Turnos Soporte Técnico
# Somos Internet — Brayan Osorio

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ─── Tipos de turno ───────────────────────────────────────────────────────────
SHIFT_T1       = "T1"       # 7:30–16:30 LV | 7:30–12:30 Sáb
SHIFT_T2       = "T2"       # 10:30–19:30 LV | 7:30–16:00 Sáb
SHIFT_DOMINGO  = "D"        # 8:00–16:00
SHIFT_DESCANSO = "DESC"     # Día libre
SHIFT_EPS      = "EPS"
SHIFT_VACACION = "V"
SHIFT_PERMISO  = "PERM"
SHIFT_CALAMIDAD = "CAL"
SHIFT_INCAPACIDAD = "INCAP"
SHIFT_OTRO     = "OTRO"

NOVEDADES = [SHIFT_EPS, SHIFT_VACACION, SHIFT_PERMISO,
             SHIFT_CALAMIDAD, SHIFT_INCAPACIDAD, SHIFT_OTRO]

SHIFT_COLORS = {
    SHIFT_T1:        "#3B82F6",   # azul
    SHIFT_T2:        "#10B981",   # verde
    SHIFT_DOMINGO:   "#8B5CF6",   # morado
    SHIFT_DESCANSO:  "#6B7280",   # gris
    SHIFT_EPS:       "#EF4444",   # rojo
    SHIFT_VACACION:  "#F59E0B",   # naranja
    SHIFT_PERMISO:   "#F97316",   # naranja oscuro
    SHIFT_CALAMIDAD: "#DC2626",   # rojo oscuro
    SHIFT_INCAPACIDAD: "#B91C1C", # rojo más oscuro
    SHIFT_OTRO:      "#9CA3AF",   # gris claro
}


class Technician(db.Model):
    """Técnico de soporte."""
    __tablename__ = "technicians"

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    code        = db.Column(db.String(20), unique=True)       # código interno
    supervisor  = db.Column(db.String(80))

    # Configuración de turno
    fixed_shift  = db.Column(db.String(10), nullable=True)     # "T1","T2",None
    tickets_only = db.Column(db.Boolean, default=False)        # exclusivo tickets
    no_sundays   = db.Column(db.Boolean, default=False)        # sin dominicales
    is_active    = db.Column(db.Boolean, default=True)

    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    # Relaciones
    assignments = db.relationship("DayAssignment", back_populates="technician",
                                  cascade="all, delete-orphan")
    novelties   = db.relationship("Novelty", back_populates="technician",
                                  cascade="all, delete-orphan")
    history     = db.relationship("TechnicianHistory", back_populates="technician",
                                  cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "supervisor": self.supervisor,
            "fixed_shift": self.fixed_shift,
            "tickets_only": self.tickets_only,
            "no_sundays": self.no_sundays,
            "is_active": self.is_active,
        }

    def __repr__(self):
        return f"<Technician {self.name}>"


class WeekSchedule(db.Model):
    """Encabezado de una semana generada."""
    __tablename__ = "week_schedules"

    id          = db.Column(db.Integer, primary_key=True)
    week_start  = db.Column(db.Date, nullable=False, unique=True)  # lunes
    week_end    = db.Column(db.Date, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes       = db.Column(db.Text)
    is_published = db.Column(db.Boolean, default=False)

    days = db.relationship("DayAssignment", back_populates="week",
                           cascade="all, delete-orphan")

    def __repr__(self):
        return f"<WeekSchedule {self.week_start}>"


class DayAssignment(db.Model):
    """Asignación de un técnico para un día específico dentro de una semana."""
    __tablename__ = "day_assignments"

    id              = db.Column(db.Integer, primary_key=True)
    week_id         = db.Column(db.Integer, db.ForeignKey("week_schedules.id"), nullable=False)
    technician_id   = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    date            = db.Column(db.Date, nullable=False)
    shift           = db.Column(db.String(10), nullable=False)  # T1, T2, D, DESC, EPS...
    is_ticket       = db.Column(db.Boolean, default=False)      # true = técnico de tickets ese día
    is_sunday_holiday = db.Column(db.Boolean, default=False)
    override_reason = db.Column(db.String(200))                 # razón si fue modificado manual
    modified_at     = db.Column(db.DateTime)

    week        = db.relationship("WeekSchedule", back_populates="days")
    technician  = db.relationship("Technician", back_populates="assignments")

    __table_args__ = (
        db.UniqueConstraint("week_id", "technician_id", "date",
                            name="uq_assignment"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "week_id": self.week_id,
            "technician_id": self.technician_id,
            "technician_name": self.technician.name if self.technician else "",
            "date": self.date.isoformat(),
            "shift": self.shift,
            "is_ticket": self.is_ticket,
            "is_sunday_holiday": self.is_sunday_holiday,
            "color": SHIFT_COLORS.get(self.shift, "#9CA3AF"),
        }

    def __repr__(self):
        return f"<DayAssignment {self.technician_id} {self.date} {self.shift}>"


class Novelty(db.Model):
    """Novedad diaria de un técnico (incapacidad, vacación, permiso, etc.)."""
    __tablename__ = "novelties"

    id              = db.Column(db.Integer, primary_key=True)
    technician_id   = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    date            = db.Column(db.Date, nullable=False)
    novelty_type    = db.Column(db.String(20), nullable=False)  # EPS, V, PERM, CAL, INCAP, OTRO
    notes           = db.Column(db.String(300))
    registered_at   = db.Column(db.DateTime, default=datetime.utcnow)
    registered_by   = db.Column(db.String(80), default="sistema")

    technician = db.relationship("Technician", back_populates="novelties")

    __table_args__ = (
        db.UniqueConstraint("technician_id", "date", name="uq_novelty_day"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "technician_id": self.technician_id,
            "technician_name": self.technician.name if self.technician else "",
            "date": self.date.isoformat(),
            "novelty_type": self.novelty_type,
            "notes": self.notes,
            "color": SHIFT_COLORS.get(self.novelty_type, "#9CA3AF"),
        }


class TechnicianHistory(db.Model):
    """Historial acumulado por técnico para decisiones de equidad del algoritmo."""
    __tablename__ = "technician_history"

    id              = db.Column(db.Integer, primary_key=True)
    technician_id   = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    week_start      = db.Column(db.Date, nullable=False)

    shift_assigned  = db.Column(db.String(10))   # T1 o T2 (turno de esa semana)
    was_ticket_week = db.Column(db.Boolean, default=False)
    sunday_count    = db.Column(db.Integer, default=0)   # domingos/festivos esa semana
    had_novelty     = db.Column(db.Boolean, default=False)

    # Acumulados hasta esa semana (para consultas rápidas)
    total_t2_weeks  = db.Column(db.Integer, default=0)
    total_ticket_weeks = db.Column(db.Integer, default=0)
    total_sundays   = db.Column(db.Integer, default=0)

    technician = db.relationship("Technician", back_populates="history")

    __table_args__ = (
        db.UniqueConstraint("technician_id", "week_start", name="uq_history_week"),
    )

    def __repr__(self):
        return f"<History {self.technician_id} {self.week_start}>"


class HolidayCalendar(db.Model):
    """Calendario de festivos para Colombia."""
    __tablename__ = "holiday_calendar"

    id      = db.Column(db.Integer, primary_key=True)
    date    = db.Column(db.Date, nullable=False, unique=True)
    name    = db.Column(db.String(100))

    def __repr__(self):
        return f"<Holiday {self.date} {self.name}>"
