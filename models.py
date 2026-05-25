# models.py -- Modelos de base de datos v2
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

SHIFT_T1 = "T1"
SHIFT_T2 = "T2"
SHIFT_DOMINGO = "D"
SHIFT_DESCANSO = "DESC"
SHIFT_EPS = "EPS"
SHIFT_VACACION = "V"
SHIFT_PERMISO = "PERM"
SHIFT_CALAMIDAD = "CAL"
SHIFT_INCAPACIDAD = "INCAP"
SHIFT_CAPACITACION = "CAP"
SHIFT_LICENCIA = "LIC"
SHIFT_AUSENTE = "AUS"
SHIFT_OTRO = "OTRO"

NOVEDADES = [SHIFT_EPS, SHIFT_VACACION, SHIFT_PERMISO, SHIFT_CALAMIDAD,
             SHIFT_INCAPACIDAD, SHIFT_CAPACITACION, SHIFT_LICENCIA,
             SHIFT_AUSENTE, SHIFT_OTRO]

ALL_SHIFTS = [SHIFT_T1, SHIFT_T2, SHIFT_DOMINGO, SHIFT_DESCANSO] + NOVEDADES

SHIFT_COLORS = {
    SHIFT_T1:          "#3B82F6",
    SHIFT_T2:          "#10B981",
    SHIFT_DOMINGO:     "#8B5CF6",
    SHIFT_DESCANSO:    "#6B7280",
    SHIFT_EPS:         "#EF4444",
    SHIFT_VACACION:    "#F59E0B",
    SHIFT_PERMISO:     "#F97316",
    SHIFT_CALAMIDAD:   "#DC2626",
    SHIFT_INCAPACIDAD: "#B91C1C",
    SHIFT_CAPACITACION:"#06B6D4",
    SHIFT_LICENCIA:    "#A855F7",
    SHIFT_AUSENTE:     "#EC4899",
    SHIFT_OTRO:        "#9CA3AF",
}

SHIFT_LABELS = {
    SHIFT_T1: "Turno 1", SHIFT_T2: "Turno 2", SHIFT_DOMINGO: "Dominical",
    SHIFT_DESCANSO: "Descanso", SHIFT_EPS: "EPS/Medico",
    SHIFT_VACACION: "Vacaciones", SHIFT_PERMISO: "Permiso",
    SHIFT_CALAMIDAD: "Calamidad", SHIFT_INCAPACIDAD: "Incapacidad",
    SHIFT_CAPACITACION: "Capacitacion", SHIFT_LICENCIA: "Licencia",
    SHIFT_AUSENTE: "Ausente", SHIFT_OTRO: "Otro",
}


class Config(db.Model):
    """Configuracion dinamica del sistema."""
    __tablename__ = "config"
    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    label = db.Column(db.String(100))

    @staticmethod
    def get(key, default=None):
        row = Config.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value, label=None):
        row = Config.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            row = Config(key=key, value=str(value), label=label)
            db.session.add(row)
        db.session.commit()


class Technician(db.Model):
    __tablename__ = "technicians"
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    code         = db.Column(db.String(20), unique=True)
    supervisor   = db.Column(db.String(80))
    fixed_shift  = db.Column(db.String(10))
    tickets_only = db.Column(db.Boolean, default=False)
    no_sundays   = db.Column(db.Boolean, default=False)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    assignments = db.relationship("DayAssignment", back_populates="technician", cascade="all, delete-orphan")
    novelties   = db.relationship("Novelty", back_populates="technician", cascade="all, delete-orphan")
    history     = db.relationship("TechnicianHistory", back_populates="technician", cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "code": self.code,
                "supervisor": self.supervisor, "fixed_shift": self.fixed_shift,
                "tickets_only": self.tickets_only, "no_sundays": self.no_sundays,
                "is_active": self.is_active}


class WeekSchedule(db.Model):
    __tablename__ = "week_schedules"
    id           = db.Column(db.Integer, primary_key=True)
    week_start   = db.Column(db.Date, nullable=False, unique=True)
    week_end     = db.Column(db.Date, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes        = db.Column(db.Text)
    is_locked    = db.Column(db.Boolean, default=False)
    days = db.relationship("DayAssignment", back_populates="week", cascade="all, delete-orphan")


class DayAssignment(db.Model):
    __tablename__ = "day_assignments"
    id               = db.Column(db.Integer, primary_key=True)
    week_id          = db.Column(db.Integer, db.ForeignKey("week_schedules.id"), nullable=False)
    technician_id    = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    date             = db.Column(db.Date, nullable=False)
    shift            = db.Column(db.String(10), nullable=False)
    is_ticket        = db.Column(db.Boolean, default=False)
    is_sunday_holiday= db.Column(db.Boolean, default=False)
    is_manual        = db.Column(db.Boolean, default=False)
    override_reason  = db.Column(db.String(200))
    modified_at      = db.Column(db.DateTime)

    week       = db.relationship("WeekSchedule", back_populates="days")
    technician = db.relationship("Technician", back_populates="assignments")

    __table_args__ = (db.UniqueConstraint("week_id", "technician_id", "date", name="uq_assignment"),)

    def to_dict(self):
        return {"id": self.id, "week_id": self.week_id,
                "technician_id": self.technician_id,
                "technician_name": self.technician.name if self.technician else "",
                "date": self.date.isoformat(), "shift": self.shift,
                "is_ticket": self.is_ticket, "is_sunday_holiday": self.is_sunday_holiday,
                "is_manual": self.is_manual,
                "color": SHIFT_COLORS.get(self.shift, "#9CA3AF"),
                "label": SHIFT_LABELS.get(self.shift, self.shift)}


class Novelty(db.Model):
    __tablename__ = "novelties"
    id             = db.Column(db.Integer, primary_key=True)
    technician_id  = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    date_start     = db.Column(db.Date, nullable=False)
    date_end       = db.Column(db.Date, nullable=False)
    novelty_type   = db.Column(db.String(20), nullable=False)
    notes          = db.Column(db.String(300))
    registered_at  = db.Column(db.DateTime, default=datetime.utcnow)
    registered_by  = db.Column(db.String(80), default="admin")

    # Compatibilidad con codigo anterior
    @property
    def date(self):
        return self.date_start

    @property
    def color(self):
        return SHIFT_COLORS.get(self.novelty_type, "#9CA3AF")

    technician = db.relationship("Technician", back_populates="novelties")

    def to_dict(self):
        return {"id": self.id, "technician_id": self.technician_id,
                "technician_name": self.technician.name if self.technician else "",
                "date_start": self.date_start.isoformat(),
                "date_end": self.date_end.isoformat(),
                "novelty_type": self.novelty_type, "notes": self.notes,
                "color": self.color}


class TechnicianHistory(db.Model):
    __tablename__ = "technician_history"
    id                 = db.Column(db.Integer, primary_key=True)
    technician_id      = db.Column(db.Integer, db.ForeignKey("technicians.id"), nullable=False)
    week_start         = db.Column(db.Date, nullable=False)
    shift_assigned     = db.Column(db.String(10))
    was_ticket_week    = db.Column(db.Boolean, default=False)
    sunday_count       = db.Column(db.Integer, default=0)
    had_novelty        = db.Column(db.Boolean, default=False)
    total_t2_weeks     = db.Column(db.Integer, default=0)
    total_ticket_weeks = db.Column(db.Integer, default=0)
    total_sundays      = db.Column(db.Integer, default=0)
    technician = db.relationship("Technician", back_populates="history")
    __table_args__ = (db.UniqueConstraint("technician_id", "week_start", name="uq_history_week"),)


class AuditLog(db.Model):
    """Registro de todos los cambios manuales."""
    __tablename__ = "audit_log"
    id            = db.Column(db.Integer, primary_key=True)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)
    entity        = db.Column(db.String(50))   # "assignment", "novelty", "config"
    entity_id     = db.Column(db.Integer)
    action        = db.Column(db.String(30))   # "create","update","delete"
    field         = db.Column(db.String(50))
    old_value     = db.Column(db.String(200))
    new_value     = db.Column(db.String(200))
    description   = db.Column(db.String(300))
    done_by       = db.Column(db.String(80), default="admin")

    @staticmethod
    def log(entity, entity_id, action, description, field=None, old=None, new=None):
        entry = AuditLog(entity=entity, entity_id=entity_id, action=action,
                         description=description, field=field,
                         old_value=str(old) if old else None,
                         new_value=str(new) if new else None)
        db.session.add(entry)


class HolidayCalendar(db.Model):
    __tablename__ = "holiday_calendar"
    id   = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(100))
