# Sistema de Turnos — Soporte Técnico FTTH
**Somos Internet · Coordinación Brayan Osorio**

App web Flask para gestión automatizada de horarios del equipo de soporte técnico telecomunicaciones.

---

## Opción 1 — Correr LOCAL (recomendada, más simple)

### Requisitos
- Python 3.10 o superior → https://www.python.org/downloads/
- Marcar "Add Python to PATH" al instalar

### Pasos

**Windows (doble clic en iniciar.bat):**
1. Abre la carpeta `soporte-turnos`
2. Doble clic en `iniciar.bat`
3. Se abre el navegador automáticamente en `http://localhost:5000`
4. Para detener: presiona `Ctrl+C` en la ventana negra

**Manual:**
```bash
cd soporte-turnos
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

La base de datos (`turnos_soporte.db`) se crea automáticamente en la misma carpeta y **persiste entre sesiones**.

---

## Opción 2 — Render gratuito (servidor en la nube)

### Importante sobre el plan gratuito
- ⚠️ El servicio **se duerme** tras 15 min sin visitas → tarda 30-60s en despertar
- ✅ La base de datos usa SQLite en disco persistente (no necesita PostgreSQL)
- ✅ 750 horas/mes gratis → suficiente para uso diario

### Pasos de despliegue

**1. Subir código a GitHub:**
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/soporte-turnos.git
git push -u origin main
```

**2. Crear servicio en Render:**
1. Ve a [render.com](https://render.com) → New → Web Service
2. Conecta tu cuenta de GitHub
3. Selecciona el repositorio `soporte-turnos`
4. Render detecta `render.yaml` automáticamente
5. Click **Deploy**

**3. Esperar ~3 minutos** a que termine el build.

**4. URL del sistema:**
`https://soporte-turnos.onrender.com` (o el nombre que Render asigne)

### Si el servicio está dormido
La primera visita del día puede tardar 30-60 segundos en cargar. Es normal en el plan gratuito. Después responde rápido.

---

## Estructura del proyecto

```
soporte-turnos/
├── app.py              # Flask app principal, rutas, configuración
├── models.py           # Modelos de base de datos (SQLAlchemy)
├── scheduler.py        # Algoritmo inteligente de generación de horarios
├── iniciar.bat         # Script para correr en Windows (doble clic)
├── requirements.txt    # Dependencias Python
├── Procfile            # Comando de inicio para Render
├── render.yaml         # Configuración automática Render (SQLite + disco)
├── templates/
│   ├── base.html       # Layout con navbar
│   ├── index.html      # Dashboard con KPIs
│   ├── schedule.html   # Horario semanal con gráficas
│   ├── novelties.html  # Registro de novedades diarias
│   ├── technicians.html # Gestión de técnicos
│   ├── history.html    # Historial y equidad de rotación
│   └── generate.html   # Generar nueva semana
└── static/
    ├── css/style.css
    └── js/main.js
```

---

## Cómo usar el sistema

### Semana nueva (cada lunes)
1. Ir a **Generar Semana**
2. Seleccionar el lunes de la semana a generar
3. Click **Generar Horario**
4. El algoritmo asigna automáticamente T1, T2, Tickets y Dominicales

### Registrar una novedad (EPS, permiso, etc.)
1. Ir a **Novedades**
2. Click **Registrar Novedad**
3. Seleccionar técnico, fecha y tipo
4. El sistema ajusta el horario automáticamente y busca reemplazo T2 si es necesario

### Ver historial de equidad
- Ir a **Historial**
- Verás semanas en T2, tickets y domingos por cada técnico
- El algoritmo usa este historial para próximas semanas

---

## Turnos (Colombia — Ley 2101/2021)

| Turno | L-V | Sábado | Horas efectivas sem. |
|-------|-----|--------|---------------------|
| T1    | 7:30–16:30 | 7:30–12:30 | 45h |
| T2    | 10:30–19:30 | 7:30–16:00 | 47.5h |
| Dom/Festivo | 8:00–16:00 | — | — |

**Jornada legal:** 44h/sem hasta jul-2026 → 42h/sem desde jul-2026.

---

## API JSON (integración con Google Sheets)

```
GET /api/week/2026-06-02      # Horario de la semana (debe ser lunes)
GET /api/technicians          # Lista de técnicos activos
GET /api/novelties/2026-06-03 # Novedades de una fecha específica
```

---

## Mejoras futuras

- [ ] Login con roles (admin / supervisor / solo lectura)
- [ ] Exportar horario a Excel (.xlsx)
- [ ] Notificación por WhatsApp al publicar horario
- [ ] Carga masiva de técnicos desde Excel
- [ ] Integración con Metabase para dashboard avanzado
- [ ] App móvil para consulta rápida por técnico
