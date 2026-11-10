from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Dashboard - Control de Circuitos", layout="wide")

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


@st.cache_data(ttl=60)
def cargar_datos_dashboard():
  try:
    client = conectar_gsheets()
    sheet = client.sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
      return pd.DataFrame()
    df.fillna("", inplace=True)
    return df
  except Exception as e:
    st.error(f"Error al conectar con Google Sheets: {e}")
    return pd.DataFrame()


df = cargar_datos_dashboard()

st.title("📊 Dashboard Gerencial - Control de Circuitos")

if df.empty:
  st.warning(
      "No hay datos registrados en la Google Sheet o la hoja está vacía."
  )
else:
  # Validar que exista la columna oficial NO. ECO
  col_eco = "NO. ECO" if "NO. ECO" in df.columns else df.columns[1]
  col_op = "OPERADOR" if "OPERADOR" in df.columns else df.columns[0]

  # ----------------------------------------------------
  # PROCESAMIENTO DE FECHAS Y TIEMPOS
  # ----------------------------------------------------
  def parse_datetime(row, f_col, h_col):
    f = str(row.get(f_col, "")).strip()
    h = str(row.get(h_col, "")).strip()
    if not f or not h:
      return pd.NaT
    try:
      return pd.to_datetime(
          f"{f} {h}", format="%d/%m/%Y %H:%M:%S", errors="coerce"
      )
    except:
      try:
        return pd.to_datetime(f"{f} {h}", errors="coerce")
      except:
        return pd.NaT


  df["DT_SALIDA_ORIGEN"] = df.apply(
      lambda r: parse_datetime(r, "FECHA SALIDA ORIGEN", "HORA SALIDA ORIGEN"),
      axis=1,
  )
  df["DT_LLEGADA_DESTINO"] = df.apply(
      lambda r: parse_datetime(
          r, "FECHA LLEGADA DESTINO", "HORA LLEGADA DESTINO"
      ),
      axis=1,
  )
  df["DT_LLEGADA_ESCALA"] = df.apply(
      lambda r: parse_datetime(
          r, "FECHA LLEGADA INTERMEDIA", "HORA LLEGADA INTERMEDIA"
      ),
      axis=1,
  )
  df["DT_SALIDA_ESCALA"] = df.apply(
      lambda r: parse_datetime(
          r, "FECHA SALIDA INTERMEDIA", "HORA SALIDA INTERMEDIA"
      ),
      axis=1,
  )

  # Estatus
  df["ESTATUS"] = df["DT_LLEGADA_DESTINO"].apply(
      lambda x: "En curso" if pd.isna(x) else "Cerrado"
  )

  # Tiempos de recorrido (Horas decimales)
  df["TIEMPO_RECORRIDO_HRS"] = (
      df["DT_LLEGADA_DESTINO"] - df["DT_SALIDA_ORIGEN"]
  ).dt.total_seconds() / 3600.0


  def formatear_horas(val):
    if pd.isna(val) or val < 0:
      return "N/A"
    hrs = int(val)
    mins = int(round((val - hrs) * 60))
    if mins == 0:
      return f"{hrs} hrs"
    return f"{hrs} hrs {mins} min"


  df["TIEMPO_RECORRIDO_STR"] = df["TIEMPO_RECORRIDO_HRS"].apply(
      formatear_horas
  )

  # Tiempos de escala / descarga
  df["TIEMPO_ESCALA_HRS"] = (
      df["DT_SALIDA_ESCALA"] - df["DT_LLEGADA_ESCALA"]
  ).dt.total_seconds() / 3600.0
  df["TIEMPO_ESCALA_STR"] = df["TIEMPO_ESCALA_HRS"].apply(formatear_horas)

  # Semana del año
  df["SEMANA"] = df["DT_SALIDA_ORIGEN"].dt.strftime("%Y-W%U")

  # ----------------------------------------------------
  # FILTROS INTELIGENTES (Sidebar)
  # ----------------------------------------------------
  st.sidebar.header("🔍 Filtros Inteligentes")

  valid_dates = df["DT_SALIDA_ORIGEN"].dropna()
  if not valid_dates.empty:
    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()
    date_range = st.sidebar.date_input(
        "Rango de Fechas (Salida)", [min_date, max_date]
    )
  else:
    date_range = []

  operadores_list = ["Todos"] + sorted(
      [str(x) for x in df[col_op].unique() if x != ""]
  )
  selected_op = st.sidebar.selectbox("Operador Específico", operadores_list)

  unidades_list = ["Todos"] + sorted(
      [str(x) for x in df[col_eco].unique() if x != ""]
  )
  selected_uni = st.sidebar.selectbox("Unidad (No. Eco)", unidades_list)

  estatus_list = ["Todos", "En curso", "Cerrado"]
  selected_est = st.sidebar.selectbox("Estatus del Circuito", estatus_list)

  # Aplicar Filtros
  df_filtered = df.copy()
  if len(date_range) == 2:
    start_d, end_d = pd.to_datetime(date_range[0]), pd.to_datetime(
        date_range[1]
    ) + pd.Timedelta(days=1)
    df_filtered = df_filtered[
        (df_filtered["DT_SALIDA_ORIGEN"] >= start_d)
        & (df_filtered["DT_SALIDA_ORIGEN"] < end_d)
    ]

  if selected_op != "Todos":
    df_filtered = df_filtered[df_filtered[col_op] == selected_op]

  if selected_uni != "Todos":
    df_filtered = df_filtered[df_filtered[col_eco] == selected_uni]

  if selected_est != "Todos":
    df_filtered = df_filtered[df_filtered["ESTATUS"] == selected_est]

  # ----------------------------------------------------
  # KPIs PRINCIPALES
  # ----------------------------------------------------
  st.subheader("📌 Indicadores Clave (KPIs)")

  total_unidades_catalogo = set([
      "388",
      "471",
      "472",
      "503",
      "540",
      "543",
      "470",
      "530",
      "539",
      "508",
      "412",
      "435",
      "538",
  ])
  unidades_en_transito = df[df["ESTATUS"] == "En curso"][col_eco].nunique()
  unidades_con_viaje_activo = set(
      df[df["ESTATUS"] == "En curso"][col_eco].unique()
  )
  unidades_sin_circuito = len(
      total_unidades_catalogo - unidades_con_viaje_activo
  )

  col1, col2, col3, col4 = st.columns(4)
  col1.metric("🚚 Unidades en Tránsito", unidades_en_transito)
  col2.metric("🟢 Unidades Libres / Sin Circuito", unidades_sin_circuito)
  col3.metric("📦 Circuitos Filtrados", len(df_filtered))

  avg_tiempo_val = df_filtered[df_filtered["TIEMPO_RECORRIDO_HRS"] > 0][
      "TIEMPO_RECORRIDO_HRS"
  ].mean()
  avg_tiempo_str = formatear_horas(avg_tiempo_val)
  col4.metric("⏱️ Tiempo Promedio Recorrido", avg_tiempo_str)

  st.markdown("---")

  # ----------------------------------------------------
  # GRÁFICAS Y TABLAS DE DETALLE
  # ----------------------------------------------------
  c1, c2 = st.columns(2)

  with c1:
    st.markdown("### 🏆 Ranking de Operadores (Circuitos Realizados)")
    if not df_filtered.empty:
      ranking_op = df_filtered[col_op].value_counts().reset_index()
      ranking_op.columns = ["Operador", "Total Circuitos"]
      st.dataframe(ranking_op, use_container_width=True)
    else:
      st.info("No hay datos para el ranking con los filtros actualizados.")

  with c2:
    st.markdown("### ⏱️ Tiempos de Descarga / Escala (Promedio)")
    df_enlace = df_filtered[
        (df_filtered["TIPO"] == "Enlace")
        & (df_filtered["TIEMPO_ESCALA_HRS"] > 0)
    ]
    if not df_enlace.empty:
      avg_escala = (
          df_enlace.groupby("PLAZA INTERMEDIA")["TIEMPO_ESCALA_HRS"]
          .mean()
          .reset_index()
      )
      avg_escala.columns = ["Plaza Escala", "Promedio en Escala"]
      avg_escala["Promedio en Escala"] = avg_escala["Promedio en Escala"].apply(
          formatear_horas
      )
      st.dataframe(avg_escala, use_container_width=True)
    else:
      st.info("No hay datos de circuitos con enlace y escalas completas.")

  st.markdown("### 📈 Servicios por Semana por Unidad")
  if not df_filtered.empty:
    servicios_semana = df_filtered.pivot_table(
        index=col_eco,
        columns="SEMANA",
        values="ORIGEN",
        aggfunc="count",
        fill_value=0,
    )
    st.dataframe(servicios_semana, use_container_width=True)
  else:
    st.info("No hay datos suficientes.")

  st.markdown("### 📋 Detalle de Circuitos")
  st.dataframe(df_filtered, use_container_width=True)
