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
    return pd.DataFrame(valores[1:], columns=headers)
  except Exception as e:
    st.error(f"Error al leer la pestaña '{nombre_pestana}': {e}")
    return pd.DataFrame()


def registrar_historial_si_cambio(
    df_actual_agrupado, nombre_historial, col_grupo, col_subgrupo
):
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
            df_ultimo[col_grupo],
            df_ultimo[col_subgrupo],
            df_ultimo["CANTIDAD"].astype(str),
        )
    )
    firma_nueva = sorted(
        zip(
            nuevo_bloque[col_grupo],
            nuevo_bloque[col_subgrupo],
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
# MAPEO DE PLAZAS EN ACUSES (BASADO EN COLUMNA P: D_Estado Destino)
# ---------------------------------------------------------
PLAZAS_OFICIALES = [
    "CANCUN",
    "MERIDA",
    "TUXTLA",
    "TOLUCA",
    "PUEBLA",
    "VILLAHERMOSA",
    "CIUDAD DEL CARMEN",
    "CAMPECHE",
    "VERACRUZ",
]


def unificar_plaza_por_estado_p(estado_col_p, destino_col_o):
  edo = str(estado_col_p).strip().upper()
  dest = str(destino_col_o).strip().upper()

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
  # Estado de México, CDMX, Guanajuato, etc.
  return "TOLUCA"


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
    rango = "1 a 5 días" if dias <= 5 else "Más de 5 días"

    areas_list.append(area)
    estatus_pend_list.append(nombre_paso)
    dias_atraso_list.append(dias)
    rango_atraso_list.append(rango)

  plazas_unificadas = [
      unificar_plaza_por_estado_p(edo, dest)
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
# PROCESAMIENTO DE ARQUEOS (PLAZA DESDE COLUMNA F: D_Plaza)
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_arqueos():
  df = leer_hoja_raw("ARQUEOS")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_mov = "Movimiento" if "Movimiento" in cols else cols[3]
  col_plaza_f = cols[5] if len(cols) > 5 else "D_Plaza"
  col_dias_at = "Dias Atraso" if "Dias Atraso" in cols else cols[11]
  col_ead = "EAD" if "EAD" in cols else cols[25]
  col_tipo_ent = "Tipo Entrega" if "Tipo Entrega" in cols else cols[33]
  col_inc = "Incidencia" if "Incidencia" in cols else cols[35]

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

  return pd.DataFrame({
      "PLAZA": plazas_clean,
      "MOVIMIENTO": mov_raw,
      "GRUPO_MOVIMIENTO": mov_raw.apply(agrupar_movimiento),
      "TIPO_GUIA": df.apply(map_tipo_guia, axis=1),
      "TIENE_INCIDENCIA": df[col_inc].apply(map_incidencia),
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
        df_ac.groupby(["PLAZA", "AREA"]).size().reset_index(name="CANTIDAD")
    )
    df_hist_ac = registrar_historial_si_cambio(
        resumen_hist_ac, "ACUSES_HISTORIAL", "PLAZA", "AREA"
    )

    col_v1, col_v2 = st.columns([2, 2])
    vista_ac = col_v1.radio(
        "Visualizar pendientes:",
        ["🏢 Por Plaza", "👥 Por Cliente"],
        horizontal=True,
    )
    filtro_rango = col_v2.radio(
        "Intervalo de atraso:",
        ["Todos", "1 a 5 días", "Más de 5 días"],
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
      cols = st.columns(3)
      for idx, plaza in enumerate(PLAZAS_OFICIALES):
        sub_p = df_ac_f[df_ac_f["PLAZA"] == plaza]
        op_val = len(sub_p[sub_p["AREA"] == "OPERACIONES"])
        adm_val = len(sub_p[sub_p["AREA"] == "ADMINISTRACIÓN"])
        mc_val = len(sub_p[sub_p["AREA"] == "MESA DE CONTROL"])

        r_1_5 = len(sub_p[sub_p["RANGO_ATRASO"] == "1 a 5 días"])
        r_mas_5 = len(sub_p[sub_p["RANGO_ATRASO"] == "Más de 5 días"])

        with cols[idx % 3]:
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
            st.caption(f"🟡 1 a 5 días: **{r_1_5}** | 🔴 +5 días: **{r_mas_5}**")

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
              st.dataframe(
                  df_det[[
                      "FOLIO_GUIA",
                      "MUNICIPIO_DESTINO",
                      "CLIENTE",
                      "AREA",
                      "ESTATUS_PENDIENTE",
                      "DIAS_ATRASO",
                      "RANGO_ATRASO",
                  ]],
                  use_container_width=True,
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

          r_1_5 = len(sub_c[sub_c["RANGO_ATRASO"] == "1 a 5 días"])
          r_mas_5 = len(sub_c[sub_c["RANGO_ATRASO"] == "Más de 5 días"])

          with cols[idx % 4]:
            with st.container(border=True):
              st.markdown(f"### 🏢 {cliente}")
              st.markdown(f"**{op_val:,}** operaciones")
              st.markdown(f"**{adm_val:,}** administración")
              st.markdown(f"**{mc_val:,}** mesa de control")
              st.caption(
                  f"🟡 1 a 5 días: **{r_1_5}** | 🔴 +5 días: **{r_mas_5}**"
              )

    st.markdown("---")
    st.subheader("📈 Tabla de Avances por Plaza (Histórico de Cortes)")
    if not df_hist_ac.empty:
      df_hist_ac["CANTIDAD"] = pd.to_numeric(
          df_hist_ac["CANTIDAD"], errors="coerce"
      ).fillna(0)
      tabla_avances_ac = (
          df_hist_ac.pivot_table(
              index="PLAZA",
              columns="CORTE_TS",
              values="CANTIDAD",
              aggfunc="sum",
              fill_value=0,
          )
          .reindex(PLAZAS_OFICIALES, fill_value=0)
          .astype(int)
      )
      if tabla_avances_ac.shape[1] >= 2:
        cortes_cols = list(tabla_avances_ac.columns)
        tabla_avances_ac["VARIACIÓN ÚLTIMO CORTE"] = (
            tabla_avances_ac[cortes_cols[-1]]
            - tabla_avances_ac[cortes_cols[-2]]
        )
      st.dataframe(tabla_avances_ac, use_container_width=True)


# =========================================================
# PESTAÑA 2: ARQUEOS
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

    tot_items = len(df_ar_f)
    vig_items = len(df_ar_f[df_ar_f["CONDICION"] == "Vigente"])
    ven_items = len(df_ar_f[df_ar_f["CONDICION"] == "Vencida"])
    inc_items = len(df_ar_f[df_ar_f["TIENE_INCIDENCIA"] == "Con Incidencia"])
    ocu_items = len(df_ar_f[df_ar_f["TIPO_GUIA"] == "OCU"])

    ka1, ka2, ka3, ka4, ka5 = st.columns(5)
    ka1.metric("📦 Carga Total (Ítems)", f"{tot_items:,}")
    ka2.metric("🟢 Carga Vigente", f"{vig_items:,}")
    ka3.metric("🔴 Carga Vencida", f"{ven_items:,}")
    ka4.metric("⚠️ Con Incidencia", f"{inc_items:,}")
    ka5.metric("🏢 Ocurres (OCU)", f"{ocu_items:,}")

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
      st.subheader("Movimiento / Estatus Actual")
      orden_grupos = ["Circuitos", "Rutas", "Inventario", "Otros Movimientos"]
      grp_mov = (
          df_ar_f.groupby(["GRUPO_MOVIMIENTO", "MOVIMIENTO"])
          .size()
          .reset_index(name="Ítems")
      )
      totales_grupo = (
          grp_mov.groupby("GRUPO_MOVIMIENTO")["Ítems"].sum().reset_index()
      )

      fig_mov = px.bar(
          grp_mov,
          x="GRUPO_MOVIMIENTO",
          y="Ítems",
          color="MOVIMIENTO",
          barmode="stack",
          category_orders={"GRUPO_MOVIMIENTO": orden_grupos},
          hover_data={
              "GRUPO_MOVIMIENTO": False,
              "MOVIMIENTO": True,
              "Ítems": True,
          },
      )
      fig_mov.add_scatter(
          x=totales_grupo["GRUPO_MOVIMIENTO"],
          y=totales_grupo["Ítems"],
          text=totales_grupo["Ítems"].apply(lambda x: f"<b>{x:,}</b>"),
          mode="text",
          textposition="top center",
          showlegend=False,
          hoverinfo="skip",
      )
      max_y = totales_grupo["Ítems"].max() if not totales_grupo.empty else 10
      fig_mov.update_yaxes(range=[0, max_y * 1.15])
      st.plotly_chart(fig_mov, use_container_width=True)

    st.markdown("---")
    st.subheader("📊 Evolución de Carga por Corte (Vigente vs. Vencida)")
    if not df_hist_ar.empty:
      df_hist_ar["CANTIDAD"] = pd.to_numeric(
          df_hist_ar["CANTIDAD"], errors="coerce"
      ).fillna(0)

      hist_filtrado = df_hist_ar.copy()
      if sel_plaza_ar != "Todas":
        hist_filtrado = hist_filtrado[hist_filtrado["PLAZA"] == sel_plaza_ar]

      resumen_cortes = (
          hist_filtrado.groupby(["CORTE_TS", "CONDICION"])["CANTIDAD"]
          .sum()
          .reset_index()
      )

      fig_ev_simple = px.bar(
          resumen_cortes,
          x="CORTE_TS",
          y="CANTIDAD",
          color="CONDICION",
          barmode="group",
          color_discrete_map={"Vigente": "#00CC96", "Vencida": "#EF553B"},
          text_auto=True,
          labels={
              "CORTE_TS": "Fecha / Hora del Corte",
              "CANTIDAD": "Total Ítems",
              "CONDICION": "Condición",
          },
      )
      st.plotly_chart(fig_ev_simple, use_container_width=True)

      with st.expander("📋 Ver Tabla de Avances de Carga Vencida por Plaza"):
        tabla_av_ar = (
            df_hist_ar[df_hist_ar["CONDICION"] == "Vencida"]
            .pivot_table(
                index="PLAZA",
                columns="CORTE_TS",
                values="CANTIDAD",
                aggfunc="sum",
                fill_value=0,
            )
            .astype(int)
        )
        if tabla_av_ar.shape[1] >= 2:
          cols_ar_c = list(tabla_av_ar.columns)
          tabla_av_ar["VARIACIÓN ÚLTIMO CORTE"] = (
              tabla_av_ar[cols_ar_c[-1]] - tabla_av_ar[cols_ar_c[-2]]
          )
        st.dataframe(tabla_av_ar, use_container_width=True)
