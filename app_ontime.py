from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Tablero Ejecutivo - Acuses y Arqueos",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------
# CONEXIÓN A GOOGLE SHEETS
# ---------------------------------------------------------
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource
def conectar_gsheets():
  secrets_dict = dict(st.secrets["gcp_service_account"])
  creds = Credentials.from_service_account_info(secrets_dict, scopes=scope)
  client = gspread.authorize(creds)
  return client.open_by_url(st.secrets["sheet_url"])


def obtener_tiempo_mexico():
  ahora = datetime.utcnow() - timedelta(hours=6)
  return ahora.strftime("%Y-%m-%d %H:%M"), ahora.strftime("%Y-%m-%d")


def limpiar_folio_exacto(val):
  if val is None or val == "":
    return ""
  if isinstance(val, (int, float)):
    return f"{int(val)}" if float(val).is_integer() else str(val)
  s = str(val).strip()
  try:
    if "E+" in s.upper() or "E-" in s.upper():
      return f"{int(float(s.replace(',', '.')))}"
  except Exception:
    pass
  return s


@st.cache_data(ttl=60)
def leer_hoja_raw(nombre_pestana):
  try:
    sh = conectar_gsheets()
    ws = sh.worksheet(nombre_pestana)
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
      return pd.DataFrame()

    headers = [str(h).strip() for h in valores[0]]
    df = pd.DataFrame(valores[1:], columns=headers)

    cols_id = {
        "FOLIO_GUIA",
        "CIP",
        "GUIA",
        "GUIA INTERNA",
        "FOLIO REFERENCIA",
        "CIP REFERENCIA",
    }
    if any(h.upper() in cols_id for h in headers):
      valores_raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
      if len(valores_raw) == len(valores):
        for idx_col, h in enumerate(headers):
          if h.upper() in cols_id:
            df[h] = [
                limpiar_folio_exacto(fila[idx_col])
                if idx_col < len(fila)
                else ""
                for fila in valores_raw[1:]
            ]
    return df
  except Exception as e:
    st.error(f"Error al leer la pestaña '{nombre_pestana}': {e}")
    return pd.DataFrame()


def mostrar_tabla_filtrable(
    df, key_prefix, cols_filtro=None, hide_index=True, column_config=None
):
  """Muestra una tabla con buscador rápido y filtros por columna."""
  if df.empty:
    st.info("Sin registros para mostrar.")
    return df

  df_work = df.copy()
  cols_validas = [c for c in (cols_filtro or []) if c in df_work.columns]

  n_cols = 1 + len(cols_validas)
  ui_cols = st.columns([2] + [1.5] * len(cols_validas))

  txt_busqueda = (
      ui_cols[0]
      .text_input(
          "🔍 Filtrar tabla (texto):",
          "",
          key=f"{key_prefix}_txt",
          placeholder="Buscar folio, guía, cliente...",
      )
      .strip()
      .upper()
  )

  for idx, col_name in enumerate(cols_validas):
    opciones = sorted(
        [
            str(v)
            for v in df_work[col_name].dropna().unique().tolist()
            if str(v).strip() != ""
        ]
    )
    seleccion = ui_cols[idx + 1].multiselect(
        f"Filtrar {col_name}:",
        options=opciones,
        default=[],
        key=f"{key_prefix}_col_{col_name}",
        placeholder="Todos",
    )
    if seleccion:
      df_work = df_work[df_work[col_name].astype(str).isin(seleccion)]

  if txt_busqueda:
    mask_txt = df_work.apply(
        lambda col: col.astype(str)
        .str.upper()
        .str.contains(txt_busqueda, na=False)
    ).any(axis=1)
    df_work = df_work[mask_txt]

  st.dataframe(
      df_work,
      use_container_width=True,
      hide_index=hide_index,
      column_config=column_config,
  )
  return df_work


def registrar_historial_si_cambio(
    df_actual_agrupado, nombre_historial, col_grupo, col_subgrupo
):
  if df_actual_agrupado.empty:
    return pd.DataFrame()

  try:
    sh = conectar_gsheets()
    try:
      ws = sh.worksheet(nombre_historial)
    except gspread.exceptions.WorksheetNotFound:
      ws = sh.add_worksheet(title=nombre_historial, rows=3000, cols=10)

    valores = ws.get_all_values()
    ts_actual, fecha_actual = obtener_tiempo_mexico()

    nuevo_bloque = df_actual_agrupado.copy()
    nuevo_bloque["CORTE_TS"] = ts_actual
    nuevo_bloque["FECHA"] = fecha_actual
    nuevo_bloque["CANTIDAD"] = nuevo_bloque["CANTIDAD"].astype(str)

    cols_esperadas = [col_grupo, col_subgrupo, "CANTIDAD", "CORTE_TS", "FECHA"]

    if not valores or len(valores) < 2:
      ws.clear()
      ws.update([cols_esperadas] + nuevo_bloque[cols_esperadas].values.tolist())
      return nuevo_bloque[cols_esperadas]

    headers_sheet = [str(h).strip() for h in valores[0]]
    if not all(c in headers_sheet for c in cols_esperadas):
      ws.clear()
      ws.update([cols_esperadas] + nuevo_bloque[cols_esperadas].values.tolist())
      return nuevo_bloque[cols_esperadas]

    df_hist = pd.DataFrame(valores[1:], columns=headers_sheet)
    df_hist = df_hist[df_hist["CORTE_TS"].astype(str).str.strip() != ""].copy()

    if df_hist.empty:
      ws.clear()
      ws.update([cols_esperadas] + nuevo_bloque[cols_esperadas].values.tolist())
      return nuevo_bloque[cols_esperadas]

    ultimo_corte = df_hist["CORTE_TS"].iloc[-1]
    df_ultimo = df_hist[df_hist["CORTE_TS"] == ultimo_corte]

    firma_anterior = sorted(
        zip(
            df_ultimo[col_grupo].astype(str),
            df_ultimo[col_subgrupo].astype(str),
            df_ultimo["CANTIDAD"].astype(str),
        )
    )
    firma_nueva = sorted(
        zip(
            nuevo_bloque[col_grupo].astype(str),
            nuevo_bloque[col_subgrupo].astype(str),
            nuevo_bloque["CANTIDAD"].astype(str),
        )
    )

    if firma_anterior != firma_nueva:
      ws.append_rows(nuevo_bloque[headers_sheet].values.tolist())
      df_hist = pd.concat(
          [df_hist, nuevo_bloque[headers_sheet]], ignore_index=True
      )

    return df_hist
  except Exception as e:
    st.warning(f"Aviso en historial '{nombre_historial}': {e}")
    return pd.DataFrame()


def construir_tabla_avances_compacta(
    df_hist, lista_plazas=None, modo_comparacion="Corte Anterior"
):
  if df_hist.empty:
    return pd.DataFrame()

  df_h = df_hist.copy()
  df_h["CANTIDAD"] = pd.to_numeric(df_h["CANTIDAD"], errors="coerce").fillna(0)

  piv = df_h.pivot_table(
      index="PLAZA",
      columns="CORTE_TS",
      values="CANTIDAD",
      aggfunc="sum",
      fill_value=0,
  ).astype(int)

  if lista_plazas:
    piv = piv.reindex(lista_plazas, fill_value=0)

  cortes = list(piv.columns)
  col_base = (
      cortes[0]
      if modo_comparacion == "Corte Inicial"
      else (cortes[-2] if len(cortes) >= 2 else cortes[0])
  )
  col_actual = cortes[-1]

  res = piv.copy()
  base_vals = res[col_base]
  act_vals = res[col_actual]

  res["VARIACIÓN"] = act_vals - base_vals

  avances_pct = []
  for b, a in zip(base_vals, act_vals):
    if b <= 0 and a <= 0:
      avances_pct.append(100.0)
    elif b <= 0 and a > 0:
      avances_pct.append(0.0)
    else:
      pct = ((b - a) / b) * 100.0
      avances_pct.append(round(max(0.0, min(100.0, pct)), 1))

  res["AVANCE (%)"] = avances_pct
  return res


# ---------------------------------------------------------
# MAPEO DE PLAZAS EN ACUSES
# ---------------------------------------------------------
PLAZAS_OFICIALES = [
    "CANCUN",
    "MERIDA",
    "TUXTLA",
    "ESTADO DE MEXICO",
    "PUEBLA",
    "GUANAJUATO",
    "VILLAHERMOSA",
    "CIUDAD DEL CARMEN",
    "CAMPECHE",
    "VERACRUZ",
]


def unificar_plaza_acuses(estado_col_p, destino_col_o):
  edo = str(estado_col_p).strip().upper()
  dest = str(destino_col_o).strip().upper()

  if (
      dest in ["METEPEC", "TULTEPEC", "PARQUE INDUSTRIAL TOLUCA 2000"]
      or "TOLUCA 2000" in dest
  ):
    return "ESTADO DE MEXICO"
  if dest in ["LEON", "LEÓN", "SILAO", "PUERTO RICO"]:
    return "GUANAJUATO"
  if dest == "PALENQUE":
    return "VILLAHERMOSA"
  if dest in ["FELIPE CARRILLO PUERTO", "CHETUMAL"]:
    return "MERIDA"

  if "QUINTANA" in edo:
    return "CANCUN"
  if "YUCATAN" in edo or "YUCATÁN" in edo:
    return "MERIDA"
  if "CHIAPAS" in edo:
    return "TUXTLA"
  if "TABASCO" in edo:
    return "VILLAHERMOSA"
  if "CAMPECHE" in edo:
    if "CARMEN" in dest or dest in ["SABANCUY", "ATASTA", "ISLA AGUADA"]:
      return "CIUDAD DEL CARMEN"
    return "CAMPECHE"
  if "VERACRUZ" in edo or "OAXACA" in edo:
    return "VERACRUZ"
  if "PUEBLA" in edo or "TLAXCALA" in edo:
    return "PUEBLA"
  if "GUANAJUATO" in edo:
    return "GUANAJUATO"

  return "ESTADO DE MEXICO"


# ---------------------------------------------------------
# PROCESAMIENTO DE ACUSES
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_acuses():
  df = leer_hoja_raw("ACUSES")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_folio = "FOLIO_GUIA" if "FOLIO_GUIA" in cols else cols[1]
  col_est_guia = "ESTATUS" if "ESTATUS" in cols else cols[3]
  col_cliente = "CLIENTE" if "CLIENTE" in cols else cols[5]
  col_f_doc = (
      "Fecha Documentacion" if "Fecha Documentacion" in cols else cols[10]
  )
  col_f_ent = "Fecha Entrega" if "Fecha Entrega" in cols else cols[11]
  col_dest_o = "Destino" if "Destino" in cols else cols[14]
  col_edo_p = "D_Estado Destino" if "D_Estado Destino" in cols else cols[15]
  col_obs = "OBSERVACIONES" if "OBSERVACIONES" in cols else cols[20]

  estatus_cols = [
      "LIQUIDAR_RUTA",
      "ENVIAR_RUTA_LIQ",
      "RECIBIR_RUTA_LIQ",
      "ASIGNADO_RETORNO",
      "MESA_DE_CONTROL",
      "ENVIADO_AL_CLIENTE",
      "CONTRARECIBO",
  ]
  estatus_cols = [c for c in estatus_cols if c in cols]

  obs_s = df[col_obs].astype(str).str.strip().str.upper()
  est_guia_s = df[col_est_guia].astype(str).str.strip().str.upper()
  f_ent_s = pd.to_datetime(df[col_f_ent], errors="coerce")
  f_doc_s = pd.to_datetime(df[col_f_doc], errors="coerce")

  anio_actual = (datetime.utcnow() - timedelta(hours=6)).year
  mask = (
      (~obs_s.str.contains("CONTRARECIBO", na=False))
      & (est_guia_s != "X")
      & (~f_ent_s.isna())
      & (f_doc_s.dt.year == anio_actual)
  )

  df_p = df[mask].copy()
  if df_p.empty:
    return pd.DataFrame()

  f_ent_p = f_ent_s[mask]
  fechas_pasos = {}
  for c in estatus_cols:
    val_clean = (
        df_p[c]
        .astype(str)
        .str.strip()
        .replace({"--": "", "nan": "", "None": ""})
    )
    fechas_pasos[c] = pd.to_datetime(val_clean, errors="coerce", dayfirst=True)

  hoy = pd.to_datetime((datetime.utcnow() - timedelta(hours=6)).date())

  areas_list = []
  estatus_pend_list = []
  dias_atraso_list = []
  rango_atraso_list = []

  for idx in range(len(df_p)):
    ultimo_idx = -1
    ultima_fecha = pd.NaT

    for p_idx, c in enumerate(estatus_cols):
      val_f = fechas_pasos[c].iloc[idx]
      if not pd.isna(val_f):
        ultimo_idx = p_idx
        ultima_fecha = val_f

    paso_pend_idx = min(ultimo_idx + 1, len(estatus_cols) - 1)
    nombre_paso = estatus_cols[paso_pend_idx] if estatus_cols else "SIN ESTATUS"

    if paso_pend_idx in [0, 1]:
      area = "OPERACIONES"
    elif paso_pend_idx in [2, 3]:
      area = "ADMINISTRACIÓN"
    else:
      area = "MESA DE CONTROL"

    ref_fecha = ultima_fecha if not pd.isna(ultima_fecha) else f_ent_p.iloc[idx]
    dias = (
        max(0, int((hoy - ref_fecha.normalize()).days))
        if not pd.isna(ref_fecha)
        else 0
    )
    rango = "0 a 5 días" if dias <= 5 else "Más de 5 días"

    areas_list.append(area)
    estatus_pend_list.append(nombre_paso)
    dias_atraso_list.append(dias)
    rango_atraso_list.append(rango)

  plazas_unificadas = [
      unificar_plaza_acuses(edo, dest)
      for edo, dest in zip(df_p[col_edo_p], df_p[col_dest_o])
  ]
  clientes_clean = (
      df_p[col_cliente]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN CLIENTE", "NAN": "SIN CLIENTE"})
  )

  return pd.DataFrame({
      "FOLIO_GUIA": df_p[col_folio].astype(str).values,
      "PLAZA": plazas_unificadas,
      "MUNICIPIO_DESTINO": (
          df_p[col_dest_o].astype(str).str.strip().str.upper().values
      ),
      "CLIENTE": clientes_clean.values,
      "AREA": areas_list,
      "ESTATUS_PENDIENTE": estatus_pend_list,
      "DIAS_ATRASO": dias_atraso_list,
      "RANGO_ATRASO": rango_atraso_list,
  })


# ---------------------------------------------------------
# PROCESAMIENTO DE ARQUEOS (BASE: COLUMNA A = CIP, FECHA PROMESA >= 01/01/2025)
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_arqueos():
  df = leer_hoja_raw("ARQUEOS")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_cip = cols[0] if len(cols) > 0 else "CIP"
  col_guia = "Guia" if "Guia" in cols else cols[1]
  col_mov = "Movimiento" if "Movimiento" in cols else cols[3]
  col_plaza_f = cols[5] if len(cols) > 5 else "D_Plaza"
  col_dias_sm = "Dias Sin Mov" if "Dias Sin Mov" in cols else cols[6]
  col_f_promesa = "Fecha Promesa" if "Fecha Promesa" in cols else cols[9]
  col_dias_at = "Dias Atraso" if "Dias Atraso" in cols else cols[11]
  col_cliente = "D_Cliente" if "D_Cliente" in cols else cols[21]
  col_ead = "EAD" if "EAD" in cols else cols[25]
  col_tipo_ent = "Tipo Entrega" if "Tipo Entrega" in cols else cols[33]
  col_inc = "Incidencia" if "Incidencia" in cols else cols[35]

  cip_series = df[col_cip].astype(str).str.strip()
  df = df[~cip_series.str.upper().isin(["", "NAN", "NONE", "NULL"])].copy()
  df[col_cip] = cip_series[df.index]
  df = df.drop_duplicates(subset=[col_cip]).copy()

  f_prom_s = pd.to_datetime(df[col_f_promesa], errors="coerce", dayfirst=True)
  df = df[f_prom_s.isna() | (f_prom_s >= pd.Timestamp("2025-01-01"))].copy()
  if df.empty:
    return pd.DataFrame()

  plaza_map = {
      "UMAN": "MERIDA",
      "UMÁN": "MERIDA",
      "MÉRIDA": "MERIDA",
      "FELIPE CARRILLO PUERTO": "MERIDA",
      "VALLADOLID": "MERIDA",
      "ESCARCEGA": "CAMPECHE",
      "ESCÁRCEGA": "CAMPECHE",
      "PLAYA DEL CARMEN": "CANCUN",
      "CANCÚN": "CANCUN",
      "MEXICO": "TOLUCA",
      "MÉXICO": "TOLUCA",
      "REFORMA": "TOLUCA",
      "TUXTLA GUTIERREZ": "TUXTLA",
      "TUXTLA GUTIÉRREZ": "TUXTLA",
      "PUEBLA CONCECION": "PUEBLA",
      "PUEBLA CONCESION": "PUEBLA",
      "TLAXCALA": "PUEBLA",
  }

  plazas_clean = (
      df[col_plaza_f]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace(plaza_map)
      .replace({"": "SIN PLAZA", "NAN": "SIN PLAZA"})
  )

  mov_raw = (
      df[col_mov]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN MOVIMIENTO", "NAN": "SIN MOVIMIENTO"})
  )

  clientes_ar_clean = (
      df[col_cliente]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN CLIENTE", "NAN": "SIN CLIENTE", "NONE": "SIN CLIENTE"})
  )

  def agrupar_movimiento(m):
    if m in ["EMBARQUE_CIRCUITO", "DESEMBARQUE_CIRCUITO"]:
      return "Circuitos"
    elif m == "EMBARQUE_RUTA":
      return "Rutas"
    elif m == "EMBARQUE_CIRCUITO_INVENTARIO":
      return "Inventario"
    else:
      return "Otros Movimientos"

  def map_tipo_guia(row):
    te = str(row[col_tipo_ent]).strip().upper()
    ead_flag = str(row[col_ead]).strip().upper()
    if "OCU" in te or ead_flag == "NO SELECCIONADO":
      return "OCU"
    return "EAD"

  def map_incidencia(val):
    v = str(val).strip()
    if v == "" or v.lower() in ["nan", "none", "null", "--"]:
      return "Sin Incidencia"
    return "Con Incidencia"

  raw_atraso = pd.to_numeric(df[col_dias_at], errors="coerce").fillna(0)
  dias_sm = (
      pd.to_numeric(df[col_dias_sm], errors="coerce")
      .fillna(0)
      .clip(lower=0)
      .astype(int)
  )

  return pd.DataFrame({
      "CIP": df[col_cip].astype(str).str.strip(),
      "GUIA": df[col_guia].astype(str).str.strip(),
      "PLAZA": plazas_clean,
      "CLIENTE": clientes_ar_clean,
      "MOVIMIENTO": mov_raw,
      "GRUPO_MOVIMIENTO": mov_raw.apply(agrupar_movimiento),
      "TIPO_GUIA": df.apply(map_tipo_guia, axis=1),
      "TIENE_INCIDENCIA": df[col_inc].apply(map_incidencia),
      "DETALLE_INCIDENCIA": df[col_inc].fillna("").astype(str).str.strip(),
      "DIAS_SIN_MOV": dias_sm,
      "DIAS_ATRASO": raw_atraso.clip(lower=0).astype(int),
      "CONDICION": raw_atraso.apply(
          lambda x: "Vencida" if x > 0 else "Vigente"
      ),
  })


# ---------------------------------------------------------
# ENCABEZADO EJECUTIVO
# ---------------------------------------------------------
col_t1, col_t2 = st.columns([5, 1])
col_t1.title("📊 Tablero Ejecutivo - Acuses y Arqueos")
if col_t2.button("🔄 Actualizar Datos", use_container_width=True):
  st.cache_data.clear()
  st.rerun()

tab_acuses, tab_arqueos = st.tabs(
    ["📄 Acuses Pendientes", "📦 Arqueos y Carga en Plaza"]
)

# =========================================================
# PESTAÑA 1: ACUSES
# =========================================================
with tab_acuses:
  df_ac = obtener_datos_acuses()

  if df_ac.empty:
    st.warning("No hay acuses pendientes registrados en la pestaña 'ACUSES'.")
  else:
    resumen_hist_ac = (
        df_ac.groupby(["PLAZA", "RANGO_ATRASO"])
        .size()
        .reset_index(name="CANTIDAD")
    )
    df_hist_ac = registrar_historial_si_cambio(
        resumen_hist_ac, "ACUSES_HISTORIAL", "PLAZA", "RANGO_ATRASO"
    )

    # -----------------------------------------------------
    # RESUMEN ESTRUCTURADO INICIAL DE ACUSES (FILTRABLE)
    # -----------------------------------------------------
    total_acuses_global = len(df_ac)
    st.markdown(f"### 📋 TOTAL ACUSES = `{total_acuses_global:,}`")

    filas_resumen_ac = []
    for plaza in PLAZAS_OFICIALES:
      sub_p = df_ac[df_ac["PLAZA"] == plaza]
      filas_resumen_ac.append({
          "Plaza": plaza,
          "Total": len(sub_p),
          "0-5": len(sub_p[sub_p["RANGO_ATRASO"] == "0 a 5 días"]),
          "+5": len(sub_p[sub_p["RANGO_ATRASO"] == "Más de 5 días"]),
          "Operaciones": len(sub_p[sub_p["AREA"] == "OPERACIONES"]),
          "Administración": len(sub_p[sub_p["AREA"] == "ADMINISTRACIÓN"]),
          "Mesa de control": len(sub_p[sub_p["AREA"] == "MESA DE CONTROL"]),
      })

    df_resumen_top_ac = pd.DataFrame(filas_resumen_ac)
    fila_total_ac = pd.DataFrame([{
        "Plaza": "TOTAL",
        "Total": int(df_resumen_top_ac["Total"].sum()),
        "0-5": int(df_resumen_top_ac["0-5"].sum()),
        "+5": int(df_resumen_top_ac["+5"].sum()),
        "Operaciones": int(df_resumen_top_ac["Operaciones"].sum()),
        "Administración": int(df_resumen_top_ac["Administración"].sum()),
        "Mesa de control": int(df_resumen_top_ac["Mesa de control"].sum()),
    }])
    df_resumen_top_ac = pd.concat(
        [df_resumen_top_ac, fila_total_ac], ignore_index=True
    )

    mostrar_tabla_filtrable(
        df_resumen_top_ac,
        key_prefix="tbl_resumen_ac",
        cols_filtro=["Plaza"],
        hide_index=True,
    )
    st.markdown("---")

    # -----------------------------------------------------
    # VISTA DE TARJETAS POR PLAZA O CLIENTE
    # -----------------------------------------------------
    col_v1, col_v2 = st.columns([2, 2])
    vista_ac = col_v1.radio(
        "Visualizar pendientes:",
        ["🏢 Por Plaza", "👥 Por Cliente"],
        horizontal=True,
    )
    filtro_rango = col_v2.radio(
        "Intervalo de atraso:",
        ["Todos", "0 a 5 días", "Más de 5 días"],
        horizontal=True,
    )

    df_ac_f = df_ac.copy()
    if filtro_rango != "Todos":
      df_ac_f = df_ac_f[df_ac_f["RANGO_ATRASO"] == filtro_rango]

    st.markdown("---")

    if "plaza_desglose" not in st.session_state:
      st.session_state.plaza_desglose = None

    if vista_ac == "🏢 Por Plaza":
      st.caption(
          "Haz clic en el botón de una plaza para abrir su desglose detallado"
          " más abajo."
      )
      cols = st.columns(5)
      for idx, plaza in enumerate(PLAZAS_OFICIALES):
        sub_p = df_ac_f[df_ac_f["PLAZA"] == plaza]
        op_val = len(sub_p[sub_p["AREA"] == "OPERACIONES"])
        adm_val = len(sub_p[sub_p["AREA"] == "ADMINISTRACIÓN"])
        mc_val = len(sub_p[sub_p["AREA"] == "MESA DE CONTROL"])

        r_0_5 = len(sub_p[sub_p["RANGO_ATRASO"] == "0 a 5 días"])
        r_mas_5 = len(sub_p[sub_p["RANGO_ATRASO"] == "Más de 5 días"])

        with cols[idx % 5]:
          with st.container(border=True):
            es_sel = st.session_state.plaza_desglose == plaza
            if st.button(
                f"{'🔵' if es_sel else '📍'} {plaza}",
                key=f"sel_p_{plaza}",
                use_container_width=True,
                type="primary" if es_sel else "secondary",
            ):
              st.session_state.plaza_desglose = None if es_sel else plaza
              st.rerun()

            st.markdown(f"**{op_val:,}** operaciones")
            st.markdown(f"**{adm_val:,}** administración")
            st.markdown(f"**{mc_val:,}** mesa de control")
            st.caption(f"🟡 0 a 5 días: **{r_0_5}** | 🔴 +5 días: **{r_mas_5}**")

      if st.session_state.plaza_desglose:
        p_sel = st.session_state.plaza_desglose
        st.markdown("---")
        with st.container(border=True):
          c_head1, c_head2 = st.columns([5, 1])
          c_head1.subheader(f"🔍 Desglose Detallado: Plaza {p_sel}")
          if c_head2.button("✖ Cerrar desglose", use_container_width=True):
            st.session_state.plaza_desglose = None
            st.rerun()

          df_det = df_ac_f[df_ac_f["PLAZA"] == p_sel]
          if df_det.empty:
            st.info("Sin pendientes en esta plaza con el filtro seleccionado.")
          else:
            d1, d2 = st.columns(2)
            with d1:
              st.markdown("**Por Área y Rango de Atraso**")
              tabla_det_area = pd.crosstab(
                  df_det["AREA"],
                  df_det["RANGO_ATRASO"],
                  margins=True,
                  margins_name="Total",
              )
              st.dataframe(tabla_det_area, use_container_width=True)

            with d2:
              st.markdown("**Por Estatus Exacto Pendiente**")
              tabla_det_est = pd.crosstab(
                  df_det["ESTATUS_PENDIENTE"],
                  df_det["RANGO_ATRASO"],
                  margins=True,
                  margins_name="Total",
              )
              st.dataframe(tabla_det_est, use_container_width=True)

            with st.expander(f"📋 Ver Folios Pendientes de {p_sel}"):
              mostrar_tabla_filtrable(
                  df_det[[
                      "FOLIO_GUIA",
                      "MUNICIPIO_DESTINO",
                      "CLIENTE",
                      "AREA",
                      "ESTATUS_PENDIENTE",
                      "DIAS_ATRASO",
                      "RANGO_ATRASO",
                  ]],
                  key_prefix=f"tbl_folios_{p_sel}",
                  cols_filtro=["CLIENTE", "AREA", "ESTATUS_PENDIENTE"],
                  hide_index=True,
              )

    else:
      buscar_cli = st.text_input("🔍 Buscar cliente:", "").strip().upper()
      clientes_unicos = df_ac_f["CLIENTE"].value_counts().index.tolist()
      if buscar_cli:
        clientes_unicos = [c for c in clientes_unicos if buscar_cli in c]

      if not clientes_unicos:
        st.info("No se encontraron clientes con ese criterio.")
      else:
        cols = st.columns(4)
        for idx, cliente in enumerate(clientes_unicos):
          sub_c = df_ac_f[df_ac_f["CLIENTE"] == cliente]
          op_val = len(sub_c[sub_c["AREA"] == "OPERACIONES"])
          adm_val = len(sub_c[sub_c["AREA"] == "ADMINISTRACIÓN"])
          mc_val = len(sub_c[sub_c["AREA"] == "MESA DE CONTROL"])

          r_0_5 = len(sub_c[sub_c["RANGO_ATRASO"] == "0 a 5 días"])
          r_mas_5 = len(sub_c[sub_c["RANGO_ATRASO"] == "Más de 5 días"])

          with cols[idx % 4]:
            with st.container(border=True):
              st.markdown(f"### 🏢 {cliente}")
              st.markdown(f"**{op_val:,}** operaciones")
              st.markdown(f"**{adm_val:,}** administración")
              st.markdown(f"**{mc_val:,}** mesa de control")
              st.caption(
                  f"🟡 0 a 5 días: **{r_0_5}** | 🔴 +5 días: **{r_mas_5}**"
              )

    # TABLA COMPACTA DE AVANCES POR PLAZA
    st.markdown("---")
    c_av1, c_av2 = st.columns([3, 2])
    c_av1.subheader("📈 Avance por Plaza — Movimiento de Atrasados (+5 días)")
    modo_ac = c_av2.radio(
        "Comparar contra:",
        ["Corte Anterior", "Corte Inicial"],
        horizontal=True,
        key="modo_av_ac",
    )
    st.caption(
        "Se mide específicamente la reducción en los acuses con **Más de 5"
        " días** de atraso (las entregas del día alimentan el rango de 0 a 5"
        " días)."
    )

    if not df_hist_ac.empty:
      df_hist_rezago = df_hist_ac[
          df_hist_ac["RANGO_ATRASO"] == "Más de 5 días"
      ].copy()
      df_hist_rezago["PLAZA"] = df_hist_rezago["PLAZA"].replace(
          {"TOLUCA": "ESTADO DE MEXICO"}
      )
      tabla_av_ac = construir_tabla_avances_compacta(
          df_hist_rezago,
          lista_plazas=PLAZAS_OFICIALES,
          modo_comparacion=modo_ac,
      ).reset_index()
      mostrar_tabla_filtrable(
          tabla_av_ac,
          key_prefix="tbl_av_acuses",
          cols_filtro=["PLAZA"],
          hide_index=True,
          column_config={
              "VARIACIÓN": st.column_config.NumberColumn(
                  "Variación",
                  help=(
                      "Negativo (-) significa que se cerraron acuses atrasados"
                  ),
                  format="%+d",
              ),
              "AVANCE (%)": st.column_config.ProgressColumn(
                  "Avance Rezago",
                  format="%.1f%%",
                  min_value=0,
                  max_value=100,
              ),
          },
      )


# =========================================================
# PESTAÑA 2: ARQUEOS (BASE: COLUMNA A = CIP)
# =========================================================
with tab_arqueos:
  df_ar = obtener_datos_arqueos()

  if df_ar.empty:
    st.warning("La pestaña 'ARQUEOS' en Google Sheets está vacía.")
  else:
    resumen_hist_ar = (
        df_ar.groupby(["PLAZA", "CONDICION"])["CIP"]
        .nunique()
        .reset_index(name="CANTIDAD")
    )
    df_hist_ar = registrar_historial_si_cambio(
        resumen_hist_ar, "ARQUEOS_HISTORIAL", "PLAZA", "CONDICION"
    )

    fa1, fa2, fa3, fa4 = st.columns(4)
    sel_plaza_ar = fa1.selectbox(
        "Plaza (Columna F):",
        ["Todas"] + sorted(df_ar["PLAZA"].unique().tolist()),
        key="p_ar",
    )
    sel_tipo_guia = fa2.selectbox(
        "Tipo de Guía:", ["Todos", "EAD", "OCU"], key="t_ar"
    )
    sel_inc = fa3.selectbox(
        "Incidencia:",
        ["Todas", "Con Incidencia", "Sin Incidencia"],
        key="i_ar",
    )
    sel_cond = fa4.selectbox(
        "Condición de Carga:", ["Todas", "Vigente", "Vencida"], key="c_ar"
    )

    df_ar_f = df_ar.copy()
    if sel_plaza_ar != "Todas":
      df_ar_f = df_ar_f[df_ar_f["PLAZA"] == sel_plaza_ar]
    if sel_tipo_guia != "Todos":
      df_ar_f = df_ar_f[df_ar_f["TIPO_GUIA"] == sel_tipo_guia]
    if sel_inc != "Todas":
      df_ar_f = df_ar_f[df_ar_f["TIENE_INCIDENCIA"] == sel_inc]
    if sel_cond != "Todas":
      df_ar_f = df_ar_f[df_ar_f["CONDICION"] == sel_cond]

    guias_validas = df_ar_f["GUIA"].replace(
        {"": pd.NA, "NAN": pd.NA, "NONE": pd.NA}
    )
    tot_guias = int(guias_validas.nunique())
    tot_cips = int(df_ar_f["CIP"].nunique())
    vig_cips = int(
        df_ar_f[df_ar_f["CONDICION"] == "Vigente"]["CIP"].nunique()
    )
    ven_cips = int(
        df_ar_f[df_ar_f["CONDICION"] == "Vencida"]["CIP"].nunique()
    )
    inc_cips = int(
        df_ar_f[df_ar_f["TIENE_INCIDENCIA"] == "Con Incidencia"][
            "CIP"
        ].nunique()
    )
    ocu_cips = int(df_ar_f[df_ar_f["TIPO_GUIA"] == "OCU"]["CIP"].nunique())

    if "kpi_arqueo_sel" not in st.session_state:
      st.session_state.kpi_arqueo_sel = None

    ka0, ka1, ka2, ka3, ka4, ka5 = st.columns(6)
    ka0.metric("🧾 Total Guías", f"{tot_guias:,}")
    ka1.metric("📦 Total CIPs (Ítems)", f"{tot_cips:,}")
    ka2.metric("🟢 CIPs Vigentes", f"{vig_cips:,}")
    ka3.metric("🔴 CIPs Vencidos", f"{ven_cips:,}")

    with ka4:
      st.metric("⚠️ Con Incidencia", f"{inc_cips:,}")
      es_inc_sel = st.session_state.kpi_arqueo_sel == "INCIDENCIA"
      if st.button(
          "Ocultar data" if es_inc_sel else "🔍 Ver data",
          key="btn_ver_inc",
          use_container_width=True,
          type="primary" if es_inc_sel else "secondary",
      ):
        st.session_state.kpi_arqueo_sel = None if es_inc_sel else "INCIDENCIA"
        st.rerun()

    with ka5:
      st.metric("🏢 Ocurres (OCU)", f"{ocu_cips:,}")
      es_ocu_sel = st.session_state.kpi_arqueo_sel == "OCU"
      if st.button(
          "Ocultar data" if es_ocu_sel else "🔍 Ver data",
          key="btn_ver_ocu",
          use_container_width=True,
          type="primary" if es_ocu_sel else "secondary",
      ):
        st.session_state.kpi_arqueo_sel = None if es_ocu_sel else "OCU"
        st.rerun()

    # DESGLOSE INMEDIATO AL SELECCIONAR "CON INCIDENCIA" U "OCURRES (OCU)"
    if st.session_state.kpi_arqueo_sel:
      modo_kpi = st.session_state.kpi_arqueo_sel
      st.markdown("---")
      with st.container(border=True):
        ck1, ck2 = st.columns([5, 1])
        if modo_kpi == "INCIDENCIA":
          df_kpi_det = df_ar_f[
              df_ar_f["TIENE_INCIDENCIA"] == "Con Incidencia"
          ]
          ck1.subheader(
              f"⚠️ Detalle de CIPs con Incidencia ({len(df_kpi_det):,} CIPs /"
              f" {df_kpi_det['GUIA'].nunique():,} guías)"
          )
        else:
          df_kpi_det = df_ar_f[df_ar_f["TIPO_GUIA"] == "OCU"]
          ck1.subheader(
              f"🏢 Detalle de CIPs en Ocurre — OCU ({len(df_kpi_det):,} CIPs /"
              f" {df_kpi_det['GUIA'].nunique():,} guías)"
          )

        if ck2.button("✖ Cerrar", key="cerrar_kpi_ar", use_container_width=True):
          st.session_state.kpi_arqueo_sel = None
          st.rerun()

        if df_kpi_det.empty:
          st.info("No hay registros con los filtros actuales.")
        else:
          r_k1, r_k2 = st.columns(2)
          with r_k1:
            st.markdown("**Resumen por Plaza y Condición (CIPs)**")
            st.dataframe(
                pd.crosstab(
                    df_kpi_det["PLAZA"],
                    df_kpi_det["CONDICION"],
                    margins=True,
                    margins_name="Total",
                ),
                use_container_width=True,
            )
          with r_k2:
            st.markdown("**Resumen por Movimiento (CIPs)**")
            st.dataframe(
                pd.crosstab(
                    df_kpi_det["MOVIMIENTO"],
                    df_kpi_det["CONDICION"],
                    margins=True,
                    margins_name="Total",
                ),
                use_container_width=True,
            )

          mostrar_tabla_filtrable(
              df_kpi_det[[
                  "CIP",
                  "GUIA",
                  "PLAZA",
                  "CLIENTE",
                  "MOVIMIENTO",
                  "CONDICION",
                  "TIPO_GUIA",
                  "DIAS_SIN_MOV",
                  "DIAS_ATRASO",
                  "DETALLE_INCIDENCIA",
              ]],
              key_prefix=f"tbl_kpi_{modo_kpi}",
              cols_filtro=["PLAZA", "CLIENTE", "MOVIMIENTO", "CONDICION"],
              hide_index=True,
          )

    # -----------------------------------------------------
    # RESUMEN EN TABLA POR PLAZA Y VISTA DE CLIENTES HOMOLOGADA CON ACUSES
    # -----------------------------------------------------
    st.markdown("---")
    vista_ar_res = st.radio(
        "Resumen de carga (Ítems / CIPs y Guías):",
        ["🏢 Por Plaza (Tabla Resumen)", "👥 Por Cliente"],
        horizontal=True,
        key="vista_res_arqueos",
    )

    if vista_ar_res == "🏢 Por Plaza (Tabla Resumen)":
      plazas_ar_ord = (
          df_ar_f.groupby("PLAZA")["CIP"]
          .nunique()
          .sort_values(ascending=False)
          .index.tolist()
      )
      if not plazas_ar_ord:
        st.info("Sin registros para mostrar por plaza.")
      else:
        filas_resumen_ar = []
        for plaza in plazas_ar_ord:
          sub_pa = df_ar_f[df_ar_f["PLAZA"] == plaza]
          filas_resumen_ar.append({
              "Plaza": plaza,
              "Ítems (CIPs)": int(sub_pa["CIP"].nunique()),
              "Guías": int(
                  sub_pa["GUIA"]
                  .replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA})
                  .nunique()
              ),
              "Vigentes": int(
                  sub_pa[sub_pa["CONDICION"] == "Vigente"]["CIP"].nunique()
              ),
              "Vencidos": int(
                  sub_pa[sub_pa["CONDICION"] == "Vencida"]["CIP"].nunique()
              ),
              "Con Incidencia": int(
                  sub_pa[sub_pa["TIENE_INCIDENCIA"] == "Con Incidencia"][
                      "CIP"
                  ].nunique()
              ),
              "Ocurres (OCU)": int(
                  sub_pa[sub_pa["TIPO_GUIA"] == "OCU"]["CIP"].nunique()
              ),
          })

        df_resumen_top_ar = pd.DataFrame(filas_resumen_ar)
        fila_total_ar = pd.DataFrame([{
            "Plaza": "TOTAL",
            "Ítems (CIPs)": int(df_resumen_top_ar["Ítems (CIPs)"].sum()),
            "Guías": tot_guias,
            "Vigentes": int(df_resumen_top_ar["Vigentes"].sum()),
            "Vencidos": int(df_resumen_top_ar["Vencidos"].sum()),
            "Con Incidencia": int(df_resumen_top_ar["Con Incidencia"].sum()),
            "Ocurres (OCU)": int(df_resumen_top_ar["Ocurres (OCU)"].sum()),
        }])
        df_resumen_top_ar = pd.concat(
            [df_resumen_top_ar, fila_total_ar], ignore_index=True
        )

        mostrar_tabla_filtrable(
            df_resumen_top_ar,
            key_prefix="tbl_resumen_ar",
            cols_filtro=["Plaza"],
            hide_index=True,
        )

    else:
      buscar_cli_ar = (
          st.text_input("🔍 Buscar cliente:", "", key="buscar_cli_ar")
          .strip()
          .upper()
      )
      clientes_ar_ord = (
          df_ar_f.groupby("CLIENTE")["CIP"]
          .nunique()
          .sort_values(ascending=False)
          .index.tolist()
      )
      if buscar_cli_ar:
        clientes_ar_ord = [c for c in clientes_ar_ord if buscar_cli_ar in c]

      if not clientes_ar_ord:
        st.info("No se encontraron clientes con ese criterio.")
      else:
        cols_c_ar = st.columns(4)
        for idx, cli in enumerate(clientes_ar_ord):
          sub_ca = df_ar_f[df_ar_f["CLIENTE"] == cli]
          cips_c = int(sub_ca["CIP"].nunique())
          guias_c = int(
              sub_ca["GUIA"]
              .replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA})
              .nunique()
          )
          vig_c = int(
              sub_ca[sub_ca["CONDICION"] == "Vigente"]["CIP"].nunique()
          )
          ven_c = int(
              sub_ca[sub_ca["CONDICION"] == "Vencida"]["CIP"].nunique()
          )
          plazas_cli = (
              sub_ca.groupby("PLAZA")["CIP"]
              .nunique()
              .sort_values(ascending=False)
          )
          plazas_txt = ", ".join(
              [f"{p} ({cnt:,})" for p, cnt in plazas_cli.items()]
          )

          with cols_c_ar[idx % 4]:
            with st.container(border=True):
              st.markdown(f"### 🏢 {cli}")
              st.markdown(f"**{cips_c:,}** ítems (CIPs)")
              st.markdown(f"**{guias_c:,}** guías")
              st.markdown(f"🟢 Vig: **{vig_c:,}** | 🔴 Ven: **{ven_c:,}**")
              st.caption(f"📍 Plazas: {plazas_txt}")

    st.markdown("---")

    # -----------------------------------------------------
    # GRÁFICA PRINCIPAL Y DESGLOSES
    # -----------------------------------------------------
    orden_grupos = ["Circuitos", "Rutas", "Inventario", "Otros Movimientos"]

    if sel_plaza_ar == "Todas":
      st.subheader("Movimiento / Estatus Actual por Plaza (CIPs)")
      st.caption(
          "💡 Haz clic en cualquier barra o color de una plaza para ver su"
          " desglose detallado abajo."
      )

      grp_plaza_mov = (
          df_ar_f.groupby(["PLAZA", "GRUPO_MOVIMIENTO"])["CIP"]
          .nunique()
          .reset_index(name="CIPs")
      )
      totales_plaza = (
          grp_plaza_mov.groupby("PLAZA")["CIPs"]
          .sum()
          .reset_index()
          .sort_values("CIPs", ascending=False)
      )
      orden_plazas = totales_plaza["PLAZA"].tolist()

      fig_mov = px.bar(
          grp_plaza_mov,
          x="PLAZA",
          y="CIPs",
          color="GRUPO_MOVIMIENTO",
          barmode="stack",
          category_orders={
              "PLAZA": orden_plazas,
              "GRUPO_MOVIMIENTO": orden_grupos,
          },
          custom_data=["PLAZA", "GRUPO_MOVIMIENTO"],
          hover_data={"PLAZA": True, "GRUPO_MOVIMIENTO": True, "CIPs": True},
          labels={"PLAZA": "Plaza", "GRUPO_MOVIMIENTO": "Tipo de Movimiento"},
      )
      fig_mov.add_scatter(
          x=totales_plaza["PLAZA"],
          y=totales_plaza["CIPs"],
          text=totales_plaza["CIPs"].apply(lambda x: f"<b>{x:,}</b>"),
          mode="text",
          textposition="top center",
          showlegend=False,
          hoverinfo="skip",
      )
      max_y = totales_plaza["CIPs"].max() if not totales_plaza.empty else 10
      fig_mov.update_yaxes(range=[0, max_y * 1.15])
      fig_mov.update_layout(clickmode="event+select")

      evento_grafica = st.plotly_chart(
          fig_mov,
          use_container_width=True,
          on_select="rerun",
          selection_mode="points",
          key="chart_ar_plazas",
      )

      puntos = []
      if evento_grafica and isinstance(evento_grafica, dict):
        puntos = evento_grafica.get("selection", {}).get("points", [])
      elif hasattr(evento_grafica, "selection"):
        puntos = evento_grafica.selection.points

      if puntos:
        pt = puntos[0]
        cdata = pt.get("customdata", [])
        plaza_clic = cdata[0] if len(cdata) > 0 else pt.get("x")
        grupo_clic = cdata[1] if len(cdata) > 1 else None

        st.markdown("---")
        with st.container(border=True):
          titulo_det = f"🔍 Desglose Detallado: Plaza **{plaza_clic}**"
          if grupo_clic:
            titulo_det += f" — Grupo **{grupo_clic}**"
          st.subheader(titulo_det)

          df_det_ar = df_ar_f[df_ar_f["PLAZA"] == plaza_clic]
          if grupo_clic:
            df_det_ar = df_det_ar[df_det_ar["GRUPO_MOVIMIENTO"] == grupo_clic]

          c_d1, c_d2 = st.columns(2)
          with c_d1:
            st.markdown("**Desglose por Movimiento Exacto y Condición (CIPs)**")
            t_mov_cond = pd.crosstab(
                df_det_ar["MOVIMIENTO"],
                df_det_ar["CONDICION"],
                margins=True,
                margins_name="Total",
            )
            st.dataframe(t_mov_cond, use_container_width=True)

          with c_d2:
            st.markdown("**Desglose por Tipo de Guía e Incidencia (CIPs)**")
            t_guia_inc = pd.crosstab(
                df_det_ar["TIPO_GUIA"],
                df_det_ar["TIENE_INCIDENCIA"],
                margins=True,
                margins_name="Total",
            )
            st.dataframe(t_guia_inc, use_container_width=True)

          with st.expander(
              f"📋 Ver CIPs / Guías ({len(df_det_ar):,} CIPs /"
              f" {df_det_ar['GUIA'].nunique():,} guías)"
          ):
            mostrar_tabla_filtrable(
                df_det_ar[[
                    "CIP",
                    "GUIA",
                    "PLAZA",
                    "CLIENTE",
                    "MOVIMIENTO",
                    "CONDICION",
                    "TIPO_GUIA",
                    "DIAS_SIN_MOV",
                    "DIAS_ATRASO",
                    "DETALLE_INCIDENCIA",
                ]],
                key_prefix=f"tbl_det_plaza_{plaza_clic}",
                cols_filtro=["CLIENTE", "MOVIMIENTO", "CONDICION", "TIPO_GUIA"],
                hide_index=True,
            )

    else:
      st.subheader(
          f"Movimiento / Estatus Actual — Plaza {sel_plaza_ar} (CIPs)"
      )
      st.caption(
          "💡 Haz clic en cualquier barra o color para ver su desglose"
          " detallado abajo."
      )

      grp_mov = (
          df_ar_f.groupby(["GRUPO_MOVIMIENTO", "MOVIMIENTO"])["CIP"]
          .nunique()
          .reset_index(name="CIPs")
      )
      totales_grupo = (
          grp_mov.groupby("GRUPO_MOVIMIENTO")["CIPs"].sum().reset_index()
      )

      fig_mov = px.bar(
          grp_mov,
          x="GRUPO_MOVIMIENTO",
          y="CIPs",
          color="MOVIMIENTO",
          barmode="stack",
          category_orders={"GRUPO_MOVIMIENTO": orden_grupos},
          custom_data=["GRUPO_MOVIMIENTO", "MOVIMIENTO"],
          hover_data={
              "GRUPO_MOVIMIENTO": False,
              "MOVIMIENTO": True,
              "CIPs": True,
          },
      )
      fig_mov.add_scatter(
          x=totales_grupo["GRUPO_MOVIMIENTO"],
          y=totales_grupo["CIPs"],
          text=totales_grupo["CIPs"].apply(lambda x: f"<b>{x:,}</b>"),
          mode="text",
          textposition="top center",
          showlegend=False,
          hoverinfo="skip",
      )
      max_y = totales_grupo["CIPs"].max() if not totales_grupo.empty else 10
      fig_mov.update_yaxes(range=[0, max_y * 1.15])
      fig_mov.update_layout(clickmode="event+select")

      evento_grafica = st.plotly_chart(
          fig_mov,
          use_container_width=True,
          on_select="rerun",
          selection_mode="points",
          key="chart_ar_detalle",
      )

      puntos = []
      if evento_grafica and isinstance(evento_grafica, dict):
        puntos = evento_grafica.get("selection", {}).get("points", [])
      elif hasattr(evento_grafica, "selection"):
        puntos = evento_grafica.selection.points

      if puntos:
        pt = puntos[0]
        cdata = pt.get("customdata", [])
        grupo_clic = cdata[0] if len(cdata) > 0 else pt.get("x")
        mov_clic = cdata[1] if len(cdata) > 1 else None

        st.markdown("---")
        with st.container(border=True):
          titulo_det = (
              f"🔍 Desglose Detallado: **{sel_plaza_ar}** — **{grupo_clic}**"
          )
          if mov_clic:
            titulo_det += f" ({mov_clic})"
          st.subheader(titulo_det)

          df_det_ar = df_ar_f[df_ar_f["GRUPO_MOVIMIENTO"] == grupo_clic]
          if mov_clic:
            df_det_ar = df_det_ar[df_det_ar["MOVIMIENTO"] == mov_clic]

          c_d1, c_d2 = st.columns(2)
          with c_d1:
            st.markdown("**Condición (Vigente vs. Vencida — CIPs)**")
            st.dataframe(
                df_det_ar["CONDICION"].value_counts().reset_index(),
                use_container_width=True,
            )
          with c_d2:
            st.markdown("**Tipo de Guía e Incidencias (CIPs)**")
            st.dataframe(
                pd.crosstab(
                    df_det_ar["TIPO_GUIA"],
                    df_det_ar["TIENE_INCIDENCIA"],
                    margins=True,
                    margins_name="Total",
                ),
                use_container_width=True,
            )

          with st.expander(
              f"📋 Ver CIPs / Guías ({len(df_det_ar):,} CIPs /"
              f" {df_det_ar['GUIA'].nunique():,} guías)"
          ):
            mostrar_tabla_filtrable(
                df_det_ar[[
                    "CIP",
                    "GUIA",
                    "CLIENTE",
                    "MOVIMIENTO",
                    "CONDICION",
                    "TIPO_GUIA",
                    "DIAS_SIN_MOV",
                    "DIAS_ATRASO",
                    "DETALLE_INCIDENCIA",
                ]],
                key_prefix=f"tbl_det_grupo_{sel_plaza_ar}_{grupo_clic}",
                cols_filtro=["CLIENTE", "MOVIMIENTO", "CONDICION", "TIPO_GUIA"],
                hide_index=True,
            )

    # ÚNICA SECCIÓN DE AVANCE DE ENTREGAS EN ARQUEOS (BASE: CIPs)
    st.markdown("---")
    ca_av1, ca_av2 = st.columns([3, 2])
    ca_av1.subheader(
        "📈 Avance de Entregas por Plaza (Salida de CIPs en Arqueo)"
    )
    modo_ar = ca_av2.radio(
        "Comparar contra:",
        ["Corte Anterior", "Corte Inicial"],
        horizontal=True,
        key="modo_av_ar",
    )
    st.caption(
        "Al entregarse un ítem (CIP) desaparece del arqueo; el avance refleja"
        " la reducción de CIPs pendientes por plaza."
    )

    if not df_hist_ar.empty:
      hist_ar_f = df_hist_ar.copy()
      if sel_plaza_ar != "Todas":
        hist_ar_f = hist_ar_f[hist_ar_f["PLAZA"] == sel_plaza_ar]

      tabla_av_ar = construir_tabla_avances_compacta(
          hist_ar_f, lista_plazas=None, modo_comparacion=modo_ar
      ).reset_index()
      mostrar_tabla_filtrable(
          tabla_av_ar,
          key_prefix="tbl_av_arqueos",
          cols_filtro=["PLAZA"],
          hide_index=True,
          column_config={
              "VARIACIÓN": st.column_config.NumberColumn(
                  "Variación (CIPs)",
                  help=(
                      "Negativo (-) significa CIPs entregados / salidas de"
                      " plaza"
                  ),
                  format="%+d",
              ),
              "AVANCE (%)": st.column_config.ProgressColumn(
                  "Avance Entregas",
                  format="%.1f%%",
                  min_value=0,
                  max_value=100,
              ),
          },
      )
