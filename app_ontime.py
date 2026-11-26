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


def normalizar_plaza(serie):
  s = (
      serie.astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN PLAZA", "NAN": "SIN PLAZA", "--": "SIN PLAZA"})
  )
  # Unificar UMAN y MERIDA
  return s.replace({"UMAN": "MERIDA", "UMÁN": "MERIDA", "MÉRIDA": "MERIDA"})


@st.cache_data(ttl=60)
def leer_hoja_raw(nombre_pestana):
  try:
    sh = conectar_gsheets()
    ws = sh.worksheet(nombre_pestana)
    valores = ws.get_all_values()
    if not valores or len(valores) < 2:
      return pd.DataFrame()
    headers = [str(h).strip() for h in valores[0]]
    return pd.DataFrame(valores[1:], columns=headers)
  except Exception as e:
    st.error(f"Error al leer la pestaña '{nombre_pestana}': {e}")
    return pd.DataFrame()


def registrar_historial_si_cambio(
    df_actual_agrupado, nombre_historial, col_estado
):
  """Guarda automáticamente una foto en el historial si cambian los totales por plaza."""
  if df_actual_agrupado.empty:
    return leer_hoja_raw(nombre_historial)

  try:
    sh = conectar_gsheets()
    ws = sh.worksheet(nombre_historial)
    valores = ws.get_all_values()

    ts_actual, fecha_actual = obtener_tiempo_mexico()
    nuevo_bloque = df_actual_agrupado.copy()
    nuevo_bloque["CORTE_TS"] = ts_actual
    nuevo_bloque["FECHA"] = fecha_actual
    nuevo_bloque["CANTIDAD"] = nuevo_bloque["CANTIDAD"].astype(str)

    if not valores or len(valores) < 2:
      ws.clear()
      ws.update([nuevo_bloque.columns.tolist()] + nuevo_bloque.values.tolist())
      return nuevo_bloque

    df_hist = pd.DataFrame(valores[1:], columns=valores[0])
    ultimo_corte = df_hist["CORTE_TS"].iloc[-1]
    df_ultimo = df_hist[df_hist["CORTE_TS"] == ultimo_corte]

    firma_anterior = sorted(
        zip(
            df_ultimo["PLAZA"],
            df_ultimo[col_estado],
            df_ultimo["CANTIDAD"].astype(str),
        )
    )
    firma_nueva = sorted(
        zip(
            nuevo_bloque["PLAZA"],
            nuevo_bloque[col_estado],
            nuevo_bloque["CANTIDAD"].astype(str),
        )
    )

    if firma_anterior != firma_nueva:
      ws.append_rows(nuevo_bloque.values.tolist())
      df_hist = pd.concat([df_hist, nuevo_bloque], ignore_index=True)

    return df_hist
  except Exception:
    return pd.DataFrame()


# ---------------------------------------------------------
# PROCESAMIENTO DE ACUSES (SOLO PENDIENTES CON FECHA ENTREGA)
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_acuses_pendientes():
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
  col_plaza = "Destino" if "Destino" in cols else cols[14]
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

  # 1. Filtrar terminados (CONTRARECIBO en OBSERVACIONES) y cancelados (ESTATUS == X)
  obs_s = df[col_obs].astype(str).str.strip().str.upper()
  est_guia_s = df[col_est_guia].astype(str).str.strip().str.upper()
  f_entrega_s = pd.to_datetime(df[col_f_ent], errors="coerce")
  f_doc_s = pd.to_datetime(df[col_f_doc], errors="coerce")

  # El primer estatus (LIQUIDAR_RUTA) parte de la Fecha de Entrega de la guía.
  # Si no tiene Fecha de Entrega, aún no entra al flujo de acuses.
  mask_pendiente = (
      (~obs_s.str.contains("CONTRARECIBO", na=False))
      & (est_guia_s != "X")
      & (~f_entrega_s.isna())
  )

  df_p = df[mask_pendiente].copy()
  if df_p.empty:
    return pd.DataFrame()

  f_ent_p = f_entrega_s[mask_pendiente]
  f_doc_p = f_doc_s[mask_pendiente]
  plaza_p = normalizar_plaza(df_p[col_plaza])
  cliente_p = (
      df_p[col_cliente]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN CLIENTE", "NAN": "SIN CLIENTE"})
  )

  # Evaluar fechas válidas en V:AB (ignorar '--' o vacíos)
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

  estatus_actual_list = []
  area_resp_list = []
  dias_atraso_list = []
  anio_doc_list = []

  for idx in range(len(df_p)):
    ultimo_idx = -1
    ultima_fecha = pd.NaT

    for p_idx, c in enumerate(estatus_cols):
      val_f = fechas_pasos[c].iloc[idx]
      if not pd.isna(val_f):
        ultimo_idx = p_idx
        ultima_fecha = val_f

    # Si el estatus tiene fecha es porque ya se hizo -> pasa al siguiente estatus y área
    paso_pend_idx = min(ultimo_idx + 1, len(estatus_cols) - 1)
    nombre_paso = estatus_cols[paso_pend_idx] if estatus_cols else "SIN ESTATUS"

    if paso_pend_idx in [0, 1]:
      area = "OPERACIONES"
    elif paso_pend_idx in [2, 3]:
      area = "ADMINISTRACIÓN"
    else:
      area = "MESA DE CONTROL"

    # Si no tiene ninguna fecha en V:AB, parte de la Fecha de Entrega de la guía
    ref_fecha = ultima_fecha if not pd.isna(ultima_fecha) else f_ent_p.iloc[idx]
    atraso = (
        max(0, int((hoy - ref_fecha.normalize()).days))
        if not pd.isna(ref_fecha)
        else 0
    )

    fd = f_doc_p.iloc[idx]
    anio_doc = str(fd.year) if not pd.isna(fd) else "SIN FECHA"

    estatus_actual_list.append(nombre_paso)
    area_resp_list.append(area)
    dias_atraso_list.append(atraso)
    anio_doc_list.append(anio_doc)

  return pd.DataFrame({
      "FOLIO_GUIA": df_p[col_folio].astype(str),
      "PLAZA": plaza_p.values,
      "CLIENTE": cliente_p.values,
      "FECHA_ENTREGA": f_ent_p.dt.strftime("%Y-%m-%d").values,
      "ANIO_DOC": anio_doc_list,
      "ESTATUS_PENDIENTE": estatus_actual_list,
      "AREA_RESPONSABLE": area_resp_list,
      "DIAS_ATRASO": dias_atraso_list,
  })


# ---------------------------------------------------------
# PROCESAMIENTO DE ARQUEOS (UMAN + MERIDA UNIFICADOS)
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_arqueos():
  df = leer_hoja_raw("ARQUEOS")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_cip = "CIP" if "CIP" in cols else cols[0]
  col_guia = "Guia" if "Guia" in cols else cols[1]
  col_mov = "Movimiento" if "Movimiento" in cols else cols[3]
  col_plaza = "D_Plaza" if "D_Plaza" in cols else cols[5]
  col_dias_sm = "Dias Sin Mov" if "Dias Sin Mov" in cols else cols[6]
  col_dias_at = "Dias Atraso" if "Dias Atraso" in cols else cols[11]
  col_cliente = "D_Cliente" if "D_Cliente" in cols else cols[21]
  col_ead = "EAD" if "EAD" in cols else cols[25]
  col_tipo_ent = "Tipo Entrega" if "Tipo Entrega" in cols else cols[33]
  col_inc = "Incidencia" if "Incidencia" in cols else cols[35]

  df_out = pd.DataFrame()
  df_out["CIP"] = df[col_cip].astype(str).str.strip()
  df_out["GUIA"] = df[col_guia].astype(str).str.strip()
  df_out["PLAZA"] = normalizar_plaza(df[col_plaza])
  df_out["MOVIMIENTO"] = (
      df[col_mov]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN MOVIMIENTO", "NAN": "SIN MOVIMIENTO"})
  )
  df_out["CLIENTE"] = df[col_cliente].astype(str).str.strip().str.upper()

  def map_tipo_guia(row):
    te = str(row[col_tipo_ent]).strip().upper()
    ead_flag = str(row[col_ead]).strip().upper()
    if "OCU" in te or ead_flag == "NO SELECCIONADO":
      return "OCU"
    return "EAD"

  df_out["TIPO_GUIA"] = df.apply(map_tipo_guia, axis=1)

  def map_incidencia(val):
    v = str(val).strip()
    if v == "" or v.lower() in ["nan", "none", "null", "--"]:
      return "Sin Incidencia"
    return "Con Incidencia"

  df_out["TIENE_INCIDENCIA"] = df[col_inc].apply(map_incidencia)
  df_out["DETALLE_INCIDENCIA"] = (
      df[col_inc].fillna("").astype(str).str.strip()
  )

  df_out["DIAS_SIN_MOV"] = (
      pd.to_numeric(df[col_dias_sm], errors="coerce")
      .fillna(0)
      .clip(lower=0)
      .astype(int)
  )
  raw_atraso = pd.to_numeric(df[col_dias_at], errors="coerce").fillna(0)

  df_out["CONDICION"] = raw_atraso.apply(
      lambda x: "Vencida" if x > 0 else "Vigente"
  )
  df_out["DIAS_ATRASO"] = raw_atraso.clip(lower=0).astype(int)

  return df_out


# ---------------------------------------------------------
# ENCABEZADO EJECUTIVO
# ---------------------------------------------------------
col_t1, col_t2 = st.columns([5, 1])
col_t1.title("📊 Tablero Ejecutivo - Acuses y Arqueos")
if col_t2.button("🔄 Actualizar Datos", use_container_width=True):
  st.cache_data.clear()
  st.rerun()

tab_acuses, tab_arqueos = st.tabs(
    ["📄 Acuses Pendientes por Plaza", "📦 Arqueos y Carga en Plaza"]
)

# =========================================================
# PESTAÑA 1: ACUSES PENDIENTES (CON TARJETAS POR PLAZA)
# =========================================================
with tab_acuses:
  df_ac = obtener_acuses_pendientes()

  if df_ac.empty:
    st.warning("No hay acuses pendientes registrados en la pestaña 'ACUSES'.")
  else:
    # Filtro opcional de año de documentación para aislar rezagos históricos de años anteriores
    anios_disp = sorted(df_ac["ANIO_DOC"].unique().tolist(), reverse=True)
    default_anio = "2026" if "2026" in anios_disp else anios_disp[0]

    col_top1, col_top2 = st.columns([2, 4])
    sel_anio = col_top1.selectbox(
        "Periodo de Documentación:",
        ["Todos"] + anios_disp,
        index=(["Todos"] + anios_disp).index(default_anio),
    )

    df_ac_periodo = (
        df_ac if sel_anio == "Todos" else df_ac[df_ac["ANIO_DOC"] == sel_anio]
    )

    # Registrar evolución histórica de pendientes por plaza
    resumen_hist_ac = (
        df_ac_periodo.groupby(["PLAZA", "AREA_RESPONSABLE"])
        .size()
        .reset_index(name="CANTIDAD")
    )
    df_hist_ac = registrar_historial_si_cambio(
        resumen_hist_ac, "ACUSES_HISTORIAL", "AREA_RESPONSABLE"
    )

    if "plaza_seleccionada" not in st.session_state:
      st.session_state.plaza_seleccionada = "TODAS"

    # Tarjetas interactivas de Totales por Plaza
    st.subheader(
        "🏢 Acuses Pendientes por Plaza (Haz clic en una plaza para ver su"
        " detalle por área)"
    )

    conteo_plazas = (
        df_ac_periodo["PLAZA"].value_counts().reset_index()
    )
    conteo_plazas.columns = ["PLAZA", "PENDIENTES"]

    # Construir cuadrícula de tarjetas (Tarjeta "TODAS" + Top Plazas)
    tarjetas = [
        {"PLAZA": "TODAS", "PENDIENTES": len(df_ac_periodo)}
    ] + conteo_plazas.to_dict(orient="records")

    cols_por_fila = 5
    for i in range(0, len(tarjetas), cols_por_fila):
      fila_tarjetas = tarjetas[i : i + cols_por_fila]
      cols = st.columns(cols_por_fila)
      for idx_c, item in enumerate(fila_tarjetas):
        plaza_nombre = item["PLAZA"]
        cant = item["PENDIENTES"]
        es_activa = st.session_state.plaza_seleccionada == plaza_nombre
        etiqueta_btn = (
            f"{'🔵 ' if es_activa else '📍 '}{plaza_nombre}\n\n**{cant:,}**"
            " pendientes"
        )
        if cols[idx_c].button(
            etiqueta_btn,
            key=f"btn_plaza_{plaza_nombre}",
            use_container_width=True,
            type="primary" if es_activa else "secondary",
        ):
          st.session_state.plaza_seleccionada = plaza_nombre
          st.rerun()

    st.markdown("---")

    # Filtrar según la tarjeta de plaza seleccionada
    plaza_act = st.session_state.plaza_seleccionada
    df_vista = (
        df_ac_periodo
        if plaza_act == "TODAS"
        else df_ac_periodo[df_ac_periodo["PLAZA"] == plaza_act]
    )

    st.subheader(
        f"📌 Responsabilidad por Área y Estatus — Plaza: {plaza_act}"
        f" ({len(df_vista):,} pendientes)"
    )

    # Tarjetas rápidas por Área Responsable de la plaza seleccionada
    a1, a2, a3 = st.columns(3)
    cnt_op = len(df_vista[df_vista["AREA_RESPONSABLE"] == "OPERACIONES"])
    cnt_adm = len(df_vista[df_vista["AREA_RESPONSABLE"] == "ADMINISTRACIÓN"])
    cnt_mc = len(df_vista[df_vista["AREA_RESPONSABLE"] == "MESA DE CONTROL"])

    a1.metric("🚛 OPERACIONES", f"{cnt_op:,} pendientes")
    a2.metric("🗂️ ADMINISTRACIÓN", f"{cnt_adm:,} pendientes")
    a3.metric("🖥️ MESA DE CONTROL", f"{cnt_mc:,} pendientes")

    g1, g2 = st.columns(2)
    with g1:
      st.markdown("**Desglose por Área y Estatus Pendiente**")
      if not df_vista.empty:
        grp_area = (
            df_vista.groupby(["AREA_RESPONSABLE", "ESTATUS_PENDIENTE"])
            .size()
            .reset_index(name="Pendientes")
        )
        fig_area = px.bar(
            grp_area,
            x="AREA_RESPONSABLE",
            y="Pendientes",
            color="ESTATUS_PENDIENTE",
            text_auto=True,
        )
        st.plotly_chart(fig_area, use_container_width=True)
      else:
        st.success("Sin acuses pendientes en esta plaza.")

    with g2:
      st.markdown("**Principales Clientes con Pendientes y 'Otros'**")
      if not df_vista.empty:
        top_cli = df_vista["CLIENTE"].value_counts().head(10).index
        df_vista = df_vista.copy()
        df_vista["CLIENTE_GRUPO"] = df_vista["CLIENTE"].apply(
            lambda x: x if x in top_cli else "OTROS"
        )
        grp_cli = df_vista["CLIENTE_GRUPO"].value_counts().reset_index()
        grp_cli.columns = ["Cliente", "Pendientes"]
        fig_cli = px.pie(grp_cli, names="Cliente", values="Pendientes", hole=0.4)
        st.plotly_chart(fig_cli, use_container_width=True)

    # Evolución histórica de pendientes
    st.subheader(f"📈 Evolución de Pendientes ({plaza_act})")
    if not df_hist_ac.empty:
      df_hist_ac["CANTIDAD"] = pd.to_numeric(
          df_hist_ac["CANTIDAD"], errors="coerce"
      ).fillna(0)
      if plaza_act != "TODAS":
        hist_plot = (
            df_hist_ac[df_hist_ac["PLAZA"] == plaza_act]
            .groupby(["CORTE_TS", "AREA_RESPONSABLE"])["CANTIDAD"]
            .sum()
            .reset_index()
        )
        fig_ev_ac = px.line(
            hist_plot,
            x="CORTE_TS",
            y="CANTIDAD",
            color="AREA_RESPONSABLE",
            markers=True,
            labels={"CORTE_TS": "Corte", "CANTIDAD": "Pendientes"},
        )
      else:
        hist_plot = (
            df_hist_ac.groupby(["CORTE_TS", "AREA_RESPONSABLE"])["CANTIDAD"]
            .sum()
            .reset_index()
        )
        fig_ev_ac = px.line(
            hist_plot,
            x="CORTE_TS",
            y="CANTIDAD",
            color="AREA_RESPONSABLE",
            markers=True,
            labels={"CORTE_TS": "Corte", "CANTIDAD": "Pendientes"},
        )
      st.plotly_chart(fig_ev_ac, use_container_width=True)

    with st.expander(f"📋 Ver Listado de Guías Pendientes ({plaza_act})"):
      st.dataframe(df_vista, use_container_width=True)


# =========================================================
# PESTAÑA 2: ARQUEOS (CON UMAN Y MERIDA UNIFICADOS)
# =========================================================
with tab_arqueos:
  df_ar = obtener_datos_arqueos()

  if df_ar.empty:
    st.warning("La pestaña 'ARQUEOS' en Google Sheets está vacía.")
  else:
    resumen_hist_ar = (
        df_ar.groupby(["PLAZA", "CONDICION"]).size().reset_index(name="CANTIDAD")
    )
    df_hist_ar = registrar_historial_si_cambio(
        resumen_hist_ar, "ARQUEOS_HISTORIAL", "CONDICION"
    )

    fa1, fa2, fa3, fa4 = st.columns(4)
    sel_plaza_ar = fa1.selectbox(
        "Plaza:",
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

    tot_items = len(df_ar_f)
    vig_items = len(df_ar_f[df_ar_f["CONDICION"] == "Vigente"])
    ven_items = len(df_ar_f[df_ar_f["CONDICION"] == "Vencida"])
    prom_sm = df_ar_f["DIAS_SIN_MOV"].mean() if tot_items > 0 else 0
    prom_at = (
        df_ar_f[df_ar_f["DIAS_ATRASO"] > 0]["DIAS_ATRASO"].mean()
        if ven_items > 0
        else 0
    )

    ka1, ka2, ka3, ka4, ka5 = st.columns(5)
    ka1.metric("📦 Carga Total (Ítems)", f"{tot_items:,}")
    ka2.metric("🟢 Carga Vigente", f"{vig_items:,}")
    ka3.metric(
        "🔴 Carga Vencida",
        f"{ven_items:,}",
        delta=f"{(ven_items/tot_items*100):.1f}%" if tot_items else "0%",
        delta_color="inverse",
    )
    ka4.metric("🛑 Prom. Días Sin Movimiento", f"{prom_sm:.1f} días")
    ka5.metric("⏰ Prom. Días de Atraso", f"{prom_at:.1f} días")

    st.markdown("---")

    ga1, ga2 = st.columns(2)
    with ga1:
      st.subheader("Carga Vigente vs. Vencida por Plaza")
      grp_ar_plaza = (
          df_ar_f.groupby(["PLAZA", "CONDICION"])
          .size()
          .reset_index(name="Ítems")
      )
      fig_ar_p = px.bar(
          grp_ar_plaza,
          x="PLAZA",
          y="Ítems",
          color="CONDICION",
          barmode="group",
          color_discrete_map={"Vigente": "#00CC96", "Vencida": "#EF553B"},
          text_auto=True,
      )
      st.plotly_chart(fig_ar_p, use_container_width=True)

    with ga2:
      st.subheader("Movimiento / Estatus Actual en Plaza")
      grp_mov = df_ar_f["MOVIMIENTO"].value_counts().reset_index()
      grp_mov.columns = ["Movimiento", "Ítems"]
      fig_mov = px.bar(
          grp_mov,
          x="Ítems",
          y="Movimiento",
          orientation="h",
          text_auto=True,
      )
      st.plotly_chart(fig_mov, use_container_width=True)

    st.subheader("📈 Evolución de Carga Vencida por Plaza")
    if not df_hist_ar.empty:
      df_hist_ar["CANTIDAD"] = pd.to_numeric(
          df_hist_ar["CANTIDAD"], errors="coerce"
      ).fillna(0)
      hist_v = df_hist_ar[df_hist_ar["CONDICION"] == "Vencida"]
      if sel_plaza_ar != "Todas":
        hist_v = hist_v[hist_v["PLAZA"] == sel_plaza_ar]
      fig_ev_ar = px.line(
          hist_v,
          x="CORTE_TS",
          y="CANTIDAD",
          color="PLAZA",
          markers=True,
          labels={"CORTE_TS": "Corte", "CANTIDAD": "Ítems Vencidos"},
      )
      st.plotly_chart(fig_ev_ar, use_container_width=True)

    with st.expander("📋 Ver Tabla Detallada de Arqueos (Ítems)"):
      st.dataframe(df_ar_f, use_container_width=True)
