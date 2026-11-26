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
    return df
  except Exception as e:
    st.error(f"Error al leer la pestaña '{nombre_pestana}': {e}")
    return pd.DataFrame()


def registrar_historial_si_cambio(df_actual_agrupado, nombre_historial, col_estado):
  """Compara el corte actual contra el último registro guardado en el historial.

  Si los números cambiaron (porque actualizaste la Google Sheet), guarda una
  nueva foto automáticamente.
  """
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

    # Verificar si hubo cambio real en los totales por plaza/estado
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
# PROCESAMIENTO DE ACUSES (Desde pestaña ACUSES)
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_acuses():
  df = leer_hoja_raw("ACUSES")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_folio = "FOLIO_GUIA" if "FOLIO_GUIA" in cols else cols[1]
  col_cliente = "CLIENTE" if "CLIENTE" in cols else cols[5]
  col_plaza = "Destino" if "Destino" in cols else cols[14]
  col_obs = "OBSERVACIONES" if "OBSERVACIONES" in cols else cols[20]
  col_f_ent = "Fecha Entrega" if "Fecha Entrega" in cols else cols[11]

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

  plaza_s = (
      df[col_plaza]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN PLAZA", "NAN": "SIN PLAZA", "--": "SIN PLAZA"})
  )
  obs_s = df[col_obs].astype(str).str.strip().str.upper()
  cliente_s = (
      df[col_cliente]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN CLIENTE", "NAN": "SIN CLIENTE"})
  )

  estado_flujo = obs_s.apply(
      lambda x: "Terminado" if "CONTRARECIBO" in x else "Pendiente"
  )
  hoy = pd.to_datetime((datetime.utcnow() - timedelta(hours=6)).date())

  fechas_pasos = {
      c: pd.to_datetime(df[c], errors="coerce", dayfirst=True)
      for c in estatus_cols
  }
  f_entrega_s = pd.to_datetime(df[col_f_ent], errors="coerce")

  estatus_actual_list = []
  area_resp_list = []
  dias_atraso_list = []

  for idx in range(len(df)):
    if estado_flujo.iloc[idx] == "Terminado":
      estatus_actual_list.append("CONTRARECIBO")
      area_resp_list.append("MESA DE CONTROL")
      dias_atraso_list.append(0)
      continue

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

    ref_fecha = (
        ultima_fecha if not pd.isna(ultima_fecha) else f_entrega_s.iloc[idx]
    )
    atraso = (
        max(0, int((hoy - ref_fecha.normalize()).days))
        if not pd.isna(ref_fecha)
        else 0
    )

    estatus_actual_list.append(nombre_paso)
    area_resp_list.append(area)
    dias_atraso_list.append(atraso)

  return pd.DataFrame({
      "FOLIO_GUIA": df[col_folio].astype(str),
      "PLAZA": plaza_s,
      "CLIENTE": cliente_s,
      "OBSERVACIONES": obs_s,
      "ESTADO_FLUJO": estado_flujo,
      "ESTATUS_ACTUAL": estatus_actual_list,
      "AREA_RESPONSABLE": area_resp_list,
      "DIAS_ATRASO": dias_atraso_list,
  })


# ---------------------------------------------------------
# PROCESAMIENTO DE ARQUEOS (Desde pestaña ARQUEOS)
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
  df_out["PLAZA"] = (
      df[col_plaza]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN PLAZA", "NAN": "SIN PLAZA"})
  )
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
# INTERFAZ EJECUTIVA PARA DIRECTIVOS
# ---------------------------------------------------------
col_t1, col_t2 = st.columns([5, 1])
col_t1.title("📊 Tablero Ejecutivo - Acuses y Arqueos")
if col_t2.button("🔄 Actualizar Datos", use_container_width=True):
  st.cache_data.clear()
  st.rerun()

tab_acuses, tab_arqueos = st.tabs(
    ["📄 Control y Flujo de Acuses", "📦 Arqueos y Carga en Plaza"]
)

# =========================================================
# PESTAÑA 1: ACUSES
# =========================================================
with tab_acuses:
  df_ac = obtener_datos_acuses()

  if df_ac.empty:
    st.warning(
        "La pestaña 'ACUSES' en Google Sheets está vacía. Pega ahí los datos de"
        " tu reporte para comenzar."
    )
  else:
    # Guardar avance automático en ACUSES_HISTORIAL si hubo cambios en la Google Sheet
    resumen_hist_ac = (
        df_ac.groupby(["PLAZA", "ESTADO_FLUJO"])
        .size()
        .reset_index(name="CANTIDAD")
    )
    df_hist_ac = registrar_historial_si_cambio(
        resumen_hist_ac, "ACUSES_HISTORIAL", "ESTADO_FLUJO"
    )

    # Filtros
    f1, f2, f3 = st.columns(3)
    sel_plaza_ac = f1.selectbox(
        "Plaza Responsable:",
        ["Todas"] + sorted(df_ac["PLAZA"].unique().tolist()),
        key="p_ac",
    )
    sel_estado_ac = f2.selectbox(
        "Estado del Flujo:",
        ["Todos", "Pendiente", "Terminado"],
        key="e_ac",
    )
    sel_area_ac = f3.selectbox(
        "Área Responsable:",
        ["Todas", "OPERACIONES", "ADMINISTRACIÓN", "MESA DE CONTROL"],
        key="a_ac",
    )

    df_ac_f = df_ac.copy()
    if sel_plaza_ac != "Todas":
      df_ac_f = df_ac_f[df_ac_f["PLAZA"] == sel_plaza_ac]
    if sel_estado_ac != "Todos":
      df_ac_f = df_ac_f[df_ac_f["ESTADO_FLUJO"] == sel_estado_ac]
    if sel_area_ac != "Todas":
      df_ac_f = df_ac_f[df_ac_f["AREA_RESPONSABLE"] == sel_area_ac]

    # KPIs
    total_ac = len(df_ac_f)
    pend_df = df_ac_f[df_ac_f["ESTADO_FLUJO"] == "Pendiente"]
    pend_ac = len(pend_df)
    term_ac = len(df_ac_f[df_ac_f["ESTADO_FLUJO"] == "Terminado"])
    prom_atraso = pend_df["DIAS_ATRASO"].mean() if pend_ac > 0 else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Acuses", f"{total_ac:,}")
    k2.metric(
        "⏳ Pendientes de Flujo",
        f"{pend_ac:,}",
        delta=f"{(pend_ac/total_ac*100):.1f}%" if total_ac else "0%",
        delta_color="inverse",
    )
    k3.metric("✅ Terminados (Contrarecibo)", f"{term_ac:,}")
    k4.metric("📅 Promedio Días Atraso (Pendientes)", f"{prom_atraso:.1f} días")

    st.markdown("---")

    # Gráficas Fila 1
    g1, g2 = st.columns(2)
    with g1:
      st.subheader("Acuses por Plaza Responsable")
      grp_plaza = (
          df_ac_f.groupby(["PLAZA", "ESTADO_FLUJO"])
          .size()
          .reset_index(name="Cantidad")
      )
      fig_plaza = px.bar(
          grp_plaza,
          x="PLAZA",
          y="Cantidad",
          color="ESTADO_FLUJO",
          barmode="stack",
          color_discrete_map={"Pendiente": "#EF553B", "Terminado": "#00CC96"},
          text_auto=True,
      )
      st.plotly_chart(fig_plaza, use_container_width=True)

    with g2:
      st.subheader("Responsabilidad por Área y Estatus (Pendientes)")
      if pend_ac > 0:
        grp_area = (
            pend_df.groupby(["AREA_RESPONSABLE", "ESTATUS_ACTUAL"])
            .size()
            .reset_index(name="Cantidad")
        )
        fig_area = px.bar(
            grp_area,
            x="AREA_RESPONSABLE",
            y="Cantidad",
            color="ESTATUS_ACTUAL",
            text_auto=True,
        )
        st.plotly_chart(fig_area, use_container_width=True)
      else:
        st.success("Sin acuses pendientes en esta selección.")

    # Gráficas Fila 2
    g3, g4 = st.columns(2)
    with g3:
      st.subheader("Principales Clientes y 'Otros'")
      top_cli = df_ac_f["CLIENTE"].value_counts().head(10).index
      df_ac_f["CLIENTE_GRUPO"] = df_ac_f["CLIENTE"].apply(
          lambda x: x if x in top_cli else "OTROS"
      )
      grp_cli = df_ac_f["CLIENTE_GRUPO"].value_counts().reset_index()
      grp_cli.columns = ["Cliente", "Cantidad"]
      fig_cli = px.pie(grp_cli, names="Cliente", values="Cantidad", hole=0.4)
      st.plotly_chart(fig_cli, use_container_width=True)

    with g4:
      st.subheader("📈 Evolución de Pendientes por Plaza")
      if not df_hist_ac.empty:
        df_hist_ac["CANTIDAD"] = pd.to_numeric(
            df_hist_ac["CANTIDAD"], errors="coerce"
        ).fillna(0)
        hist_p = df_hist_ac[df_hist_ac["ESTADO_FLUJO"] == "Pendiente"]
        if sel_plaza_ac != "Todas":
          hist_p = hist_p[hist_p["PLAZA"] == sel_plaza_ac]
        fig_ev_ac = px.line(
            hist_p,
            x="CORTE_TS",
            y="CANTIDAD",
            color="PLAZA",
            markers=True,
            labels={"CORTE_TS": "Corte", "CANTIDAD": "Pendientes"},
        )
        st.plotly_chart(fig_ev_ac, use_container_width=True)

    with st.expander("📋 Ver Detalle de Acuses Pendientes"):
      st.dataframe(pend_df, use_container_width=True)

# =========================================================
# PESTAÑA 2: ARQUEOS
# =========================================================
with tab_arqueos:
  df_ar = obtener_datos_arqueos()

  if df_ar.empty:
    st.warning(
        "La pestaña 'ARQUEOS' en Google Sheets está vacía. Pega ahí los datos"
        " de tu reporte para comenzar."
    )
  else:
    # Guardar avance automático en ARQUEOS_HISTORIAL si hubo cambios en la Google Sheet
    resumen_hist_ar = (
        df_ar.groupby(["PLAZA", "CONDICION"]).size().reset_index(name="CANTIDAD")
    )
    df_hist_ar = registrar_historial_si_cambio(
        resumen_hist_ar, "ARQUEOS_HISTORIAL", "CONDICION"
    )

    # Filtros
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

    # KPIs
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
