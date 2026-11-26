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
# MAPEO DE LAS 8 PLAZAS OFICIALES EN ACUSES
# ---------------------------------------------------------
PLAZAS_8 = [
    "CANCUN",
    "MERIDA",
    "TUXTLA",
    "TOLUCA",
    "VILLAHERMOSA",
    "CIUDAD DEL CARMEN",
    "CAMPECHE",
    "VERACRUZ",
]


def unificar_plaza_acuses(destino_val, estado_val):
  dest = str(destino_val).strip().upper()
  edo = str(estado_val).strip().upper()

  if "CARMEN" in dest or dest in ["SABANCUY", "ATASTA", "ISLA AGUADA"]:
    return "CIUDAD DEL CARMEN"
  if "QUINTANA" in edo or dest in [
      "CANCUN",
      "PLAYA DEL CARMEN",
      "CHETUMAL",
      "TULUM",
      "COZUMEL",
      "FELIPE CARRILLO PUERTO",
      "PUERTO MORELOS",
      "BACALAR",
      "ISLA MUJERES",
  ]:
    return "CANCUN"
  if "YUCATAN" in edo or dest in [
      "MERIDA",
      "UMAN",
      "VALLADOLID",
      "KANASIN",
      "TIZIMIN",
      "PROGRESO",
      "MOTUL",
      "TICUL",
      "TEKAX",
      "CONKAL",
      "IZAMAL",
  ]:
    return "MERIDA"
  if (
      "CHIAPAS" in edo
      or "TUXTLA" in dest
      or dest
      in [
          "TAPACHULA",
          "SAN CRISTOBAL DE LAS CASAS",
          "PALENQUE",
          "COMITAN",
          "OCOSINGO",
          "VILLAFLORES",
          "CHIAPA DE CORZO",
          "TONALA",
          "CINTALAPA",
      ]
  ):
    return "TUXTLA"
  if "TABASCO" in edo or dest in [
      "VILLAHERMOSA",
      "CARDENAS",
      "MACUSPANA",
      "PARAISO",
      "COMALCALCO",
      "EMILIANO ZAPATA",
      "CUNDUACAN",
      "TENOSIQUE DE PINO SUAREZ",
      "TEAPA",
      "HUIMANGUILLO",
  ]:
    return "VILLAHERMOSA"
  if "CAMPECHE" in edo or dest in [
      "CAMPECHE",
      "ESCARCEGA",
      "CHAMPOTON",
      "CALKINI",
      "HECELCHAKAN",
      "CANDELARIA",
      "TENABO",
      "HOPELCHEN",
  ]:
    return "CAMPECHE"
  if (
      "VERACRUZ" in edo
      or "OAXACA" in edo
      or dest
      in [
          "VERACRUZ",
          "BOCA DEL RIO",
          "XALAPA",
          "CORDOBA",
          "ORIZABA",
          "COATZACOALCOS",
          "POZA RICA",
          "MINATITLAN",
          "TUXTEPEC",
          "SAN ANDRES TUXTLA",
          "TIERRA BLANCA",
          "COSAMALOAPAN",
          "ACAYUCAN",
          "SALINA CRUZ",
          "OAXACA",
      ]
  ):
    return "VERACRUZ"
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
  col_est_guia = "ESTATUS" if "ESTATUS" in cols else cols[3]
  col_cliente = "CLIENTE" if "CLIENTE" in cols else cols[5]
  col_f_doc = (
      "Fecha Documentacion" if "Fecha Documentacion" in cols else cols[10]
  )
  col_f_ent = "Fecha Entrega" if "Fecha Entrega" in cols else cols[11]
  col_dest = "Destino" if "Destino" in cols else cols[14]
  col_edo_dest = "D_Estado Destino" if "D_Estado Destino" in cols else cols[15]
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

  # Solo pendientes activos: sin CONTRARECIBO, no canceladas (X), con Fecha Entrega y año vigente
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

  fechas_pasos = {}
  for c in estatus_cols:
    val_clean = (
        df_p[c]
        .astype(str)
        .str.strip()
        .replace({"--": "", "nan": "", "None": ""})
    )
    fechas_pasos[c] = pd.to_datetime(val_clean, errors="coerce", dayfirst=True)

  areas_list = []
  for idx in range(len(df_p)):
    ultimo_idx = -1
    for p_idx, c in enumerate(estatus_cols):
      if not pd.isna(fechas_pasos[c].iloc[idx]):
        ultimo_idx = p_idx
    paso_pend_idx = min(ultimo_idx + 1, len(estatus_cols) - 1)
    if paso_pend_idx in [0, 1]:
      areas_list.append("OPERACIONES")
    elif paso_pend_idx in [2, 3]:
      areas_list.append("ADMINISTRACIÓN")
    else:
      areas_list.append("MESA DE CONTROL")

  plazas_unificadas = [
      unificar_plaza_acuses(d, e)
      for d, e in zip(df_p[col_dest], df_p[col_edo_dest])
  ]
  clientes_clean = (
      df_p[col_cliente]
      .astype(str)
      .str.strip()
      .str.upper()
      .replace({"": "SIN CLIENTE", "NAN": "SIN CLIENTE"})
  )

  return pd.DataFrame({
      "PLAZA": plazas_unificadas,
      "CLIENTE": clientes_clean.values,
      "AREA": areas_list,
  })


# ---------------------------------------------------------
# PROCESAMIENTO DE ARQUEOS
# ---------------------------------------------------------
@st.cache_data(ttl=60)
def obtener_datos_arqueos():
  df = leer_hoja_raw("ARQUEOS")
  if df.empty:
    return pd.DataFrame()

  cols = list(df.columns)
  col_mov = "Movimiento" if "Movimiento" in cols else cols[3]
  col_plaza = "D_Plaza" if "D_Plaza" in cols else cols[5]
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
  }

  plazas_clean = (
      df[col_plaza]
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
# INTERFAZ EJECUTIVA
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
# PESTAÑA 1: ACUSES (POR PLAZA Y POR CLIENTE)
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

    vista_ac = st.radio(
        "Selecciona cómo visualizar los pendientes:",
        ["🏢 Por Plaza", "👥 Por Cliente"],
        horizontal=True,
    )
    st.markdown("---")

    if vista_ac == "🏢 Por Plaza":
      # Tabla cruzada asegurando las 8 plazas oficiales
      tabla_plaza = pd.crosstab(df_ac["PLAZA"], df_ac["AREA"]).reindex(
          index=PLAZAS_8,
          columns=["OPERACIONES", "ADMINISTRACIÓN", "MESA DE CONTROL"],
          fill_value=0,
      )

      cols = st.columns(4)
      for idx, plaza in enumerate(PLAZAS_8):
        op_val = int(tabla_plaza.loc[plaza, "OPERACIONES"])
        adm_val = int(tabla_plaza.loc[plaza, "ADMINISTRACIÓN"])
        mc_val = int(tabla_plaza.loc[plaza, "MESA DE CONTROL"])

        with cols[idx % 4]:
          with st.container(border=True):
            st.markdown(f"### 📍 {plaza}")
            st.markdown(f"**{op_val:,}** operaciones")
            st.markdown(f"**{adm_val:,}** administración")
            st.markdown(f"**{mc_val:,}** mesa de control")

      if not df_hist_ac.empty:
        st.markdown("---")
        st.subheader("📈 Avance Histórico por Plaza")
        df_hist_ac["CANTIDAD"] = pd.to_numeric(
            df_hist_ac["CANTIDAD"], errors="coerce"
        ).fillna(0)
        hist_tot = (
            df_hist_ac.groupby(["CORTE_TS", "PLAZA"])["CANTIDAD"]
            .sum()
            .reset_index()
        )
        fig_ev = px.line(
            hist_tot,
            x="CORTE_TS",
            y="CANTIDAD",
            color="PLAZA",
            markers=True,
            labels={"CORTE_TS": "Corte", "CANTIDAD": "Pendientes"},
        )
        st.plotly_chart(fig_ev, use_container_width=True)

    else:
      buscar_cli = (
          st.text_input(
              "🔍 Buscar cliente (deja vacío para ver todos los principales):",
              "",
          )
          .strip()
          .upper()
      )

      tabla_cli = pd.crosstab(df_ac["CLIENTE"], df_ac["AREA"]).reindex(
          columns=["OPERACIONES", "ADMINISTRACIÓN", "MESA DE CONTROL"],
          fill_value=0,
      )
      tabla_cli["TOTAL"] = tabla_cli.sum(axis=1)
      tabla_cli = tabla_cli.sort_values("TOTAL", ascending=False).drop(
          columns=["TOTAL"]
      )

      if buscar_cli:
        tabla_cli = tabla_cli[
            tabla_cli.index.str.contains(buscar_cli, na=False)
        ]

      if tabla_cli.empty:
        st.info("No se encontraron clientes con ese nombre.")
      else:
        cols = st.columns(4)
        for idx, cliente in enumerate(tabla_cli.index):
          op_val = int(tabla_cli.loc[cliente, "OPERACIONES"])
          adm_val = int(tabla_cli.loc[cliente, "ADMINISTRACIÓN"])
          mc_val = int(tabla_cli.loc[cliente, "MESA DE CONTROL"])

          with cols[idx % 4]:
            with st.container(border=True):
              st.markdown(f"### 🏢 {cliente}")
              st.markdown(f"**{op_val:,}** operaciones")
              st.markdown(f"**{adm_val:,}** administración")
              st.markdown(f"**{mc_val:,}** mesa de control")


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

    # 5 Tarjetas principales (sin promedios de días)
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
          hover_data={"GRUPO_MOVIMIENTO": False, "MOVIMIENTO": True, "Ítems": True},
      )
      # Mostrar el total acumulado arriba de cada barra agrupada
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

    # Evolución histórica Arqueos
    if not df_hist_ar.empty:
      st.subheader("📈 Evolución de Carga Vencida por Plaza")
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
