import os, sqlite3
from datetime import date
from flask import Flask, g, render_template, request, redirect, url_for, flash

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
        ('P00001', 'Arroz extra', 'kg', 4.50),
        ('P00002', 'Azúcar rubia', 'kg', 3.80),
        ('P00003', 'Leche evaporada', 'lt', 5.20),
        ('P00004', 'Aceite vegetal', 'lt', 9.90),
        ('P00005', 'Pan de molde', 'paq', 7.50),
        ('P00006', 'Huevos', 'doc', 10.00),
        ('P00007', 'Agua mineral', 'bot', 2.50),
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

    # Calcular subtotales y totales
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

    igv = round(max(0.0, subtot) * IGV_TASA, 2)        # 1) IGV sobre SUBTOTAL
    total_bruto = round(subtot + igv, 2)
    desc_v = round(total_bruto * (des_pct/100.0), 2)    # 2) % sobre TOTAL BRUTO
    tot = round(total_bruto - desc_v, 2)                # 3) Total final

    if tot < 0:
        flash("El descuento supera el total de la compra.", "warning")
        return redirect(url_for("factura_nueva"))

    try:
        db.execute("""INSERT INTO FACTURA
              (NFAC,FECEM,FECVEN,"DESC",IGV,TOTFAC,CODI,EMPR,CODV)
              VALUES (?,?,?,?,?,?,?,?,?)""",
           (nfac, fecem, fecven, desc_v, igv, tot, codi, "E0001", codv))
        db.executemany("""INSERT INTO DETALLE_FACTURA (NFAC,CODT,CANT,PRECLI)
                          VALUES (?,?,?,?)""", lineas)
        db.commit()
        flash(f"Factura {nfac} creada. Total: {tot:.2f}", "success")
    except sqlite3.IntegrityError as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("facturas"))

if __name__ == "__main__":
    app.run(debug=True)
