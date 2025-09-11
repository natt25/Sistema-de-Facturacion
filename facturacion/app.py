import os, sqlite3
from datetime import date
from flask import Flask, g, render_template, request, redirect, url_for, flash

import re

from flask import send_file  # <-- añade esto
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors


# --------- Validaciones comunes ----------
def _not_empty(*vals):
    return all(v is not None and str(v).strip() != "" for v in vals)

def valid_dni(dni: str) -> bool:
    return bool(re.fullmatch(r"\d{8}", dni or ""))

def valid_telf(telf: str) -> bool:
    return bool(re.fullmatch(r"\d{6,15}", telf or ""))  # ajusta rango si quieres

def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))

def valid_ruc(ruc: str) -> bool:
    return bool(re.fullmatch(r"\d{11}", ruc or ""))

def valid_precio(precio: str) -> bool:
    try:
        return float(precio) >= 0
    except:
        return False

def valid_unidad(unid: str) -> bool:
    return len((unid or "").strip()) <= 10 and _not_empty(unid)


DB_PATH = os.path.join(os.path.dirname(__file__), "facturacion.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
IGV_TASA = 0.18  # 18% Perú

app = Flask(__name__)
app.secret_key = "cambia-esta-clave"

# ---------- DB helpers ----------
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        need_init = not os.path.exists(DB_PATH)
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        if need_init:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                db.executescript(f.read())
            seed(db)
            db.commit()
    return db

@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, "_db", None)
    if db: db.close()

def seed(db):
    # Datos de ejemplo mínimos
    db.executemany("INSERT OR IGNORE INTO CLIENTE VALUES (?,?,?,?,?,?,?,?,?)", [
        ("C00001","12345678","Ana","Pérez","999111222","ana@demo.com","Av. Aviación","Cercado","Arequipa"),
        ("C00002","87654321","Luis","Soto","999333444","luis@demo.com","Jr. Unión","Cayma","Arequipa"),
    ])
    db.executemany("INSERT OR IGNORE INTO EMPRESA VALUES (?,?,?,?,?,?)", [
        ("E0001","20123456789","Empresa ABC SAC","Av. Metropolitana 100","Cercado","Arequipa")
    ])
    db.executemany("INSERT OR IGNORE INTO VENDEDOR VALUES (?,?,?)", [
        ("V0001","María","Lopez"), ("V0002","Jorge","Torres")
    ])
    db.executemany("INSERT OR IGNORE INTO PRODUCTO VALUES (?,?,?,?)", [
        ('P00001','Cuaderno cuadriculado A4 100 hojas','pza',9.50),
        ('P00002','Folder manila A4','pza',0.80),
        ('P00003','Archivador palanca A4','pza',18.00),
        ('P00004','Goma en barra 40 g','pza',3.50),
        ('P00005','Plumón para pizarra negro','pza',4.00)
    ])

# ---------- Rutas ----------
@app.route("/")
def index():
    db = get_db()
    tot_clientes = db.execute("SELECT COUNT(*) c FROM CLIENTE").fetchone()["c"]
    tot_productos = db.execute("SELECT COUNT(*) c FROM PRODUCTO").fetchone()["c"]
    tot_facturas  = db.execute("SELECT COUNT(*) c FROM FACTURA").fetchone()["c"]
    return render_template("index.html", tot_clientes=tot_clientes, tot_productos=tot_productos, tot_facturas=tot_facturas)

# --- Clientes ---
@app.route("/clientes")
def clientes():
    db = get_db()
    rows = db.execute("SELECT * FROM CLIENTE ORDER BY CODI").fetchall()
    return render_template("clientes.html", rows=rows)

@app.route("/clientes/nuevo", methods=["POST"])
def clientes_nuevo():
    db = get_db()
    f = request.form

    CODI = f["CODI"].strip()
    DNI  = (f.get("DNI") or "").strip()
    NOMB = (f.get("NOMB") or "").strip()
    APEL = (f.get("APEL") or "").strip()
    TELF = (f.get("TELF") or "").strip()
    EMAIL= (f.get("EMAIL") or "").strip()
    CALLE= (f.get("CALLE") or "").strip()
    DIST = (f.get("DIST") or "").strip()
    CIUD = (f.get("CIUD") or "").strip()

    # Reglas mínimas
    if not _not_empty(CODI, DNI, NOMB, APEL):
        flash("CODI, DNI, NOMB y APEL son obligatorios.", "warning"); return redirect(url_for("clientes"))
    if not valid_dni(DNI):
        flash("DNI inválido (8 dígitos).", "warning"); return redirect(url_for("clientes"))
    if TELF and not valid_telf(TELF):
        flash("Teléfono inválido (6–15 dígitos).", "warning"); return redirect(url_for("clientes"))
    if EMAIL and not valid_email(EMAIL):
        flash("Email inválido.", "warning"); return redirect(url_for("clientes"))

    # Unicidad
    if db.execute("SELECT 1 FROM CLIENTE WHERE DNI = ?", (DNI,)).fetchone():
        flash("DNI ya registrado.", "warning"); return redirect(url_for("clientes"))
    if EMAIL and db.execute("SELECT 1 FROM CLIENTE WHERE EMAIL = ?", (EMAIL,)).fetchone():
        flash("Email ya registrado.", "warning"); return redirect(url_for("clientes"))
    if TELF and db.execute("SELECT 1 FROM CLIENTE WHERE TELF = ?", (TELF,)).fetchone():
        flash("Teléfono ya registrado.", "warning"); return redirect(url_for("clientes"))

    try:
        db.execute("""INSERT INTO CLIENTE (CODI,DNI,NOMB,APEL,TELF,EMAIL,CALLE,DIST,CIUD)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (CODI, DNI, NOMB, APEL, TELF, EMAIL, CALLE, DIST, CIUD))
        db.commit()
        flash("Cliente creado", "success")
    except sqlite3.IntegrityError as e:
        # Plan B: si por carrera concurrente pega UNIQUE, avisa igual
        flash(f"Violación de unicidad: {e}", "danger")
    return redirect(url_for("clientes"))


# --- Vendedores ---
@app.route("/vendedores")
def vendedores():
    db = get_db()
    rows = db.execute("SELECT * FROM VENDEDOR ORDER BY CODV").fetchall()
    return render_template("vendedores.html", rows=rows)

@app.route("/vendedores/nuevo", methods=["POST"])
def vendedores_nuevo():
    db = get_db()
    f = request.form
    try:
        db.execute("INSERT INTO VENDEDOR (CODV,NOMB,APEL) VALUES (?,?,?)",
                   (f["CODV"], f["NOMB"], f["APEL"]))
        db.commit()
        flash("Vendedor creado", "success")
    except sqlite3.IntegrityError as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("vendedores"))

# --- Productos ---
@app.route("/productos")
def productos():
    db = get_db()
    rows = db.execute("SELECT * FROM PRODUCTO ORDER BY CODT").fetchall()
    return render_template("productos.html", rows=rows)

@app.route("/productos/nuevo", methods=["POST"])
def productos_nuevo():
    db = get_db()
    f = request.form

    CODT = (f.get("CODT") or "").strip()
    NOMB = (f.get("NOMB") or "").strip()
    UNID = (f.get("UNID") or "").strip()
    PREC = (f.get("PREC") or "").strip()

    if not _not_empty(CODT, NOMB, UNID, PREC):
        flash("CODT, NOMB, UNID y PREC son obligatorios.", "warning"); return redirect(url_for("productos"))
    if not valid_unidad(UNID):
        flash("UNID inválida (1–10 caracteres).", "warning"); return redirect(url_for("productos"))
    if not valid_precio(PREC):
        flash("PREC inválido (número ≥ 0).", "warning"); return redirect(url_for("productos"))

    if db.execute("SELECT 1 FROM PRODUCTO WHERE NOMB = ? AND UNID = ?", (NOMB, UNID)).fetchone():
        flash("Producto duplicado (Nombre + Unidad).", "warning"); return redirect(url_for("productos"))
    if db.execute("SELECT 1 FROM PRODUCTO WHERE lower(NOMB)=lower(?)", (NOMB,)).fetchone():
            flash("Ya existe un producto con ese nombre.", "warning")
            return redirect(url_for("productos"))

    try:
        db.execute("INSERT INTO PRODUCTO (CODT,NOMB,UNID,PREC) VALUES (?,?,?,?)",
                   (CODT, NOMB, UNID, float(PREC)))
        db.commit()
        flash("Producto creado", "success")
    except sqlite3.IntegrityError as e:
        flash(f"Violación de unicidad: {e}", "danger")
    return redirect(url_for("productos"))


# --- Facturas (listado) ---
@app.route("/facturas")
def facturas():
    db = get_db()
    q = """
    SELECT F.NFAC, F.FECEM, F.FECVEN, F."DESC", F.IGV, F.TOTFAC,
           C.NOMB||' '||C.APEL as cliente,
           V.NOMB||' '||V.APEL as vendedor,
           E.RAZS as empresa
    FROM FACTURA F
    JOIN CLIENTE  C ON C.CODI=F.CODI
    JOIN VENDEDOR V ON V.CODV=F.CODV
    JOIN EMPRESA  E ON E.EMPR=F.EMPR
    ORDER BY F.FECEM DESC, F.NFAC DESC
    """
    rows = db.execute(q).fetchall()
    return render_template("facturas.html", rows=rows)

# --- Nueva factura (form + alta) ---
@app.route("/facturas/nueva")
def factura_nueva():
    db = get_db()
    clientes  = db.execute("SELECT CODI, NOMB||' '||APEL AS nom FROM CLIENTE ORDER BY nom").fetchall()
    vendedores= db.execute("SELECT CODV, NOMB||' '||APEL AS nom FROM VENDEDOR ORDER BY nom").fetchall()
    productos = db.execute("SELECT CODT, NOMB, UNID, PREC FROM PRODUCTO ORDER BY NOMB").fetchall()
    return render_template("factura_nueva.html", hoy=date.today().isoformat(),
                           clientes=clientes, vendedores=vendedores, productos=productos)

@app.post("/facturas/crear")
def facturas_crear():
    db = get_db()
    f = request.form

    # Datos cabecera
    nfac   = f["NFAC"]
    fecem  = f["FECEM"]
    fecven = f["FECVEN"]
    codi   = f["CODI"]
    empr   = "E0001"
    codv   = f["CODV"]
    # Leer % de descuento
    des_pct = float(f.get("DESCPCT", "0") or 0)
    if des_pct < 0 or des_pct > 100:
        flash("Descuento (%) inválido. Debe estar entre 0 y 100.", "warning")
        return redirect(url_for("factura_nueva"))

    # Items dinámicos: vienen como listas paralelas
    codts  = request.form.getlist("CODT[]")
    cants  = request.form.getlist("CANT[]")

    if not codts or not cants:
        flash("Debe agregar al menos un producto.", "warning")
        return redirect(url_for("factura_nueva"))

    # Subtotal de líneas
    subtot = 0.0
    lineas = []
    for codt, cant_str in zip(codts, cants):
        cant = int(cant_str or 0)
        if cant <= 0:
            continue
        fila = db.execute("SELECT PREC FROM PRODUCTO WHERE CODT=?", (codt,)).fetchone()
        if not fila:
            continue
        precio = float(fila["PREC"])
        precli = round(precio * cant, 2)
        subtot += precli
        lineas.append((nfac, codt, cant, precli))

    # Descuento (%) sobre el SUBTOTAL
    des_pct = float(f.get("DESCPCT", "0") or 0)
    if des_pct < 0 or des_pct > 100:
        flash("Descuento (%) inválido. Debe estar entre 0 y 100.", "warning")
        return redirect(url_for("factura_nueva"))

    desc_v = round(max(0.0, subtot) * (des_pct / 100.0), 2)

    # Base imponible luego del descuento
    base = max(0.0, round(subtot - desc_v, 2))

    # IGV sobre la BASE (ya descontada)
    igv = round(base * IGV_TASA, 2)

    # Total = base + IGV
    tot = round(base + igv, 2)

    if tot < 0:
        flash("El descuento supera el subtotal.", "warning")
        return redirect(url_for("factura_nueva"))

    # Guardar (DESC se almacena como monto en S/)
    db.execute("""INSERT INTO FACTURA
                (NFAC,FECEM,FECVEN,"DESC",IGV,TOTFAC,CODI,EMPR,CODV)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (nfac, fecem, fecven, desc_v, igv, tot, codi, "E0001", codv))
    db.executemany("""INSERT INTO DETALLE_FACTURA (NFAC,CODT,CANT,PRECLI)
                    VALUES (?,?,?,?)""", lineas)
    db.commit()
    try:
        flash(f"Factura {nfac} creada. Total: {tot:.2f}", "success")
    except sqlite3.IntegrityError as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("facturas"))

@app.get("/facturas/<nfac>/pdf")
def factura_pdf(nfac):
    db = get_db()

    # Cabecera de factura: FACTURA + CLIENTE + EMPRESA + VENDEDOR
    cab = db.execute("""
        SELECT F.NFAC, F.FECEM, F.FECVEN, F."DESC" AS DESC_M, F.IGV, F.TOTFAC,
               C.CODI, C.NOMB||' '||C.APEL AS cliente, C.DNI, C.CALLE AS c_calle, C.DIST AS c_dist, C.CIUD AS c_ciud,
               E.EMPR, E.RAZS, E.RUC, E.CALLE AS e_calle, E.DIST AS e_dist, E.CIUD AS e_ciud,
               V.CODV, V.NOMB||' '||V.APEL AS vendedor
        FROM FACTURA F
        JOIN CLIENTE  C ON C.CODI=F.CODI
        JOIN VENDEDOR V ON V.CODV=F.CODV
        JOIN EMPRESA  E ON E.EMPR=F.EMPR
        WHERE F.NFAC=?
    """, (nfac,)).fetchone()

    if not cab:
        flash("Factura no encontrada", "warning")
        return redirect(url_for("facturas"))

    # Detalle de líneas
    det = db.execute("""
        SELECT D.NFAC, D.CODT, P.NOMB AS producto, D.CANT, D.PRECLI
        FROM DETALLE_FACTURA D
        JOIN PRODUCTO P ON P.CODT = D.CODT
        WHERE D.NFAC=?
        ORDER BY P.NOMB
    """, (nfac,)).fetchall()

    # Subtotal calculado a partir de PRECLI (coherente con el almacenamiento)
    subtot = sum(float(r["PRECLI"]) for r in det)
    desc_m = float(cab["DESC_M"])  # monto de descuento guardado
    igv    = float(cab["IGV"])
    total  = float(cab["TOTFAC"])
    base   = max(0.0, round(subtot - desc_m, 2))   # tu regla actual: descuento sobre subtotal, IGV sobre base

    # --- Componer PDF ---
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    W, H = A4
    x_m, y = 20*mm, H - 20*mm

    def draw_text(txt, x, y, size=10, bold=False):
        if bold:
            c.setFont("Helvetica-Bold", size)
        else:
            c.setFont("Helvetica", size)
        c.drawString(x, y, txt)

    # Encabezado empresa
    draw_text(cab["RAZS"], x_m, y, 14, bold=True); y -= 6*mm
    draw_text(f"RUC: {cab['RUC']}", x_m, y); y -= 5*mm
    draw_text(f"Dirección: {cab['e_calle']}, {cab['e_dist']} - {cab['e_ciud']}", x_m, y); y -= 10*mm

    # Título y datos de factura
    draw_text(f"FACTURA N° {cab['NFAC']}", x_m, y, 13, bold=True); y -= 6*mm
    draw_text(f"Fecha de emisión: {cab['FECEM'] or ''}", x_m, y); y -= 5*mm
    if cab["FECVEN"]:
        draw_text(f"Fecha de vencimiento: {cab['FECVEN']}", x_m, y); y -= 6*mm
    else:
        y -= 3*mm

    # Datos del cliente
    draw_text("Cliente:", x_m, y, bold=True); y -= 5*mm
    draw_text(f"{cab['cliente']}  (DNI: {cab['DNI']})", x_m, y); y -= 5*mm
    draw_text(f"Dirección: {cab['c_calle']}, {cab['c_dist']} - {cab['c_ciud']}", x_m, y); y -= 8*mm

    # Tabla de detalle
    # Cabecera
    c.setFillColor(colors.black)
    c.rect(x_m, y-6*mm, W-2*x_m, 8*mm, stroke=1, fill=0)
    draw_text("Código",  x_m + 2*mm, y-2*mm, 10, True)
    draw_text("Producto",x_m + 30*mm, y-2*mm, 10, True)
    draw_text("Cant.",   x_m + 120*mm, y-2*mm, 10, True)
    draw_text("P. Unit", x_m + 135*mm, y-2*mm, 10, True)
    draw_text("Subtotal",x_m + 160*mm, y-2*mm, 10, True)
    y -= 10*mm

    # Filas
    for r in det:
        punit = (float(r["PRECLI"]) / float(r["CANT"])) if r["CANT"] else 0.0
        draw_text(r["CODT"], x_m + 2*mm, y)
        draw_text(r["producto"][:40], x_m + 30*mm, y)
        draw_text(str(r["CANT"]), x_m + 120*mm, y)
        draw_text(f"S/ {punit:.2f}", x_m + 135*mm, y)
        draw_text(f"S/ {float(r['PRECLI']):.2f}", x_m + 160*mm, y)
        y -= 6*mm
        if y < 40*mm:  # salto de página simple
            c.showPage()
            y = H - 30*mm

    # Totales
    y -= 4*mm
    c.line(x_m + 120*mm, y, W - 20*mm, y); y -= 2*mm
    draw_text(f"Subtotal:    S/ {subtot:.2f}", x_m + 125*mm, y); y -= 5*mm
    draw_text(f"Descuento:   S/ {desc_m:.2f}", x_m + 125*mm, y); y -= 5*mm
    draw_text(f"Base:        S/ {base:.2f}",   x_m + 125*mm, y); y -= 5*mm
    draw_text(f"IGV (18%):   S/ {igv:.2f}",   x_m + 125*mm, y); y -= 5*mm
    draw_text(f"TOTAL:       S/ {total:.2f}", x_m + 125*mm, y, 12, True)

    # Pie
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(x_m, 15*mm, f"Vendedor: {cab['vendedor']}  |  Generado por el sistema de facturación")
    c.showPage()
    c.save()
    buffer.seek(0)

    filename = f"Factura_{cab['NFAC']}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")



if __name__ == "__main__":
    app.run(debug=True)
