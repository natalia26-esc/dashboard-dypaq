import streamlit as st
import pandas as pd
import plotly.express as px
import datetime

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA
# ---------------------------------------------------------
st.set_page_config(
    page_title="Torre de Control DYPAQ - Circuitos",
    layout="wide",
    page_icon="📊"
)

st.title("📊 Torre de Control de Circuitos Nacionales | DYPAQ")
st.markdown("### Indicadores de Rendimiento de Red: Análisis de Despacho, Arribo e Incidencias")
st.markdown("---")

# ---------------------------------------------------------
# FUNCIONES AUXILIARES DE TIEMPO Y NORMALIZACIÓN
# ---------------------------------------------------------
def formatear_minutos_a_string(minutos_totales):
    if pd.isna(minutos_totales) or minutos_totales <= 0:
        return "0 min"
    hrs = int(minutos_totales // 60)
    mins = int(minutos_totales % 60)
    if hrs > 0:
        return f"{hrs} hrs {mins} min" if mins > 0 else f"{hrs} hrs"
    return f"{mins} min"

def normalizar_texto(texto):
    if pd.isna(texto):
        return ""
    txt = str(texto).upper().strip()
    replacements = (
        ("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"),
        ("MERIDA ANDREA", "MERIDA"), ("CDC-MERIDA", "MERIDA"),
        ("VHS", "VILLAHERMOSA"), ("VSA", "VILLAHERMOSA"),
        ("TLC", "TOLUCA"), ("VER", "VERACRUZ"), ("CUN", "CANCUN"),
        ("TX", "TUXTLA"), ("TUXTLA GUTIERREZ", "TUXTLA")
    )
    for a, b in replacements:
        txt = txt.replace(a, b)
    return txt

# ---------------------------------------------------------
# CARGA DE ARCHIVO
# ---------------------------------------------------------
uploaded_file = st.file_uploader("📂 Cargar Matriz Unificada de Control de Vehículos", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        # Cargar libro de Excel
        if uploaded_file.name.endswith('.xlsx'):
            excel_obj = pd.ExcelFile(uploaded_file)
            sheet_names = excel_obj.sheet_names
            
            # 1. Horarios Establecidos
            if 'HORARIOS ESTABLECIDOS' in sheet_names:
                df_horarios = pd.read_excel(uploaded_file, sheet_name='HORARIOS ESTABLECIDOS')
            else:
                df_horarios = pd.read_excel(uploaded_file, sheet_name=0)
            
            # 2. Consolidador de Plazas
            plazas_sheets = [s for s in sheet_names if s not in ['HORARIOS ESTABLECIDOS', 'COMENTARIOS', 'Dashboard', 'PORTADA']]
            df_list = []
            for sheet in plazas_sheets:
                df_temp = pd.read_excel(uploaded_file, sheet_name=sheet)
                df_temp.columns = df_temp.columns.astype(str).str.strip().str.upper()
                df_list.append(df_temp)
            df_raw = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
        else:
            df_raw = pd.read_csv(uploaded_file)
            df_horarios = pd.DataFrame()

        # Limpieza de nombres de columnas
        df_raw.columns = df_raw.columns.astype(str).str.strip().str.upper()
        
        # Renombrar columnas clave si varían
        rename_dict = {}
        for col in df_raw.columns:
            if 'FECHA' in col and 'SALIDA' in col: rename_dict[col] = 'FECHA SALIDA'
            elif 'HORA' in col and 'SALIDA' in col: rename_dict[col] = 'HORA SALIDA'
            elif 'FECHA' in col and 'LLEGADA' in col: rename_dict[col] = 'FECHA LLEGADA'
            elif 'HORA' in col and 'LLEGADA' in col: rename_dict[col] = 'HORA LLEGADA'
        df_raw.rename(columns=rename_dict, inplace=True)

        # ---------------------------------------------------------
        # PROCESAMIENTO Y REGLAS DE NEGOCIO (TOLERANCIA 15 MIN)
        # ---------------------------------------------------------
        df_proc = df_raw.copy()
        
        # Normalización de Plazas
        df_proc['ORIGEN_NORM'] = df_proc['ORIGEN'].apply(normalizar_texto)
        df_proc['DESTINO_NORM'] = df_proc['DESTINO'].apply(normalizar_texto)
        df_proc['RUTA_KEY'] = df_proc['ORIGEN_NORM'] + "-" + df_proc['DESTINO_NORM']

        # Conversión de fechas y horas
        df_proc['FECHA_SALIDA_DT'] = pd.to_datetime(df_proc['FECHA SALIDA'], errors='coerce')
        df_proc['FECHA_LLEGADA_DT'] = pd.to_datetime(df_proc['FECHA LLEGADA DESTINO FINAL'], errors='coerce')

        # Procesar Horarios Teóricos de la pestaña de Horarios
        if not df_horarios.empty:
            df_horarios.columns = df_horarios.columns.astype(str).str.strip().str.upper()
            df_horarios['ORIGEN_NORM'] = df_horarios['ORIGEN'].apply(normalizar_texto)
            df_horarios['DESTINO_NORM'] = df_horarios['DESTINO'].apply(normalizar_texto)
            df_horarios['RUTA_KEY'] = df_horarios['ORIGEN_NORM'] + "-" + df_horarios['DESTINO_NORM']
            
            # Mapear horas teóricas
            map_salida = dict(zip(df_horarios['RUTA_KEY'], df_horarios['HORA SALIDA']))
            map_llegada = dict(zip(df_horarios['RUTA_KEY'], df_horarios['HORA LLEGADA DESTINO FINAL']))
            
            df_proc['HORA_SALIDA_TEO'] = df_proc['RUTA_KEY'].map(map_salida)
            df_proc['HORA_LLEGADA_TEO'] = df_proc['RUTA_KEY'].map(map_llegada)
        else:
            df_proc['HORA_SALIDA_TEO'] = None
            df_proc['HORA_LLEGADA_TEO'] = None

        # --- EVALUACIÓN ON TIME (TOLERANCIA: HASTA +15 MIN) ---
        def evaluar_salida(row):
            if pd.isna(row['HORA SALIDA']) or pd.isna(row['HORA_SALIDA_TEO']):
                return 'SIN DATO', 0
            try:
                h_real = pd.to_datetime(str(row['HORA SALIDA'])).time()
                h_teo = pd.to_datetime(str(row['HORA_SALIDA_TEO'])).time()
                m_real = h_real.hour * 60 + h_real.minute
                m_teo = h_teo.hour * 60 + h_teo.minute
                diff = m_real - m_teo
                
                # Tolerancia: Salida a tiempo o anticipada es ON TIME, retraso <= 15 min es ON TIME
                if diff <= 15:
                    return 'ON TIME', max(0, diff)
                else:
                    return 'SALIDA TARDÍA', diff
            except:
                return 'SIN DATO', 0

        def evaluar_llegada(row):
            if pd.isna(row['HORA LLEGADA DESTINO FINAL']) or pd.isna(row['HORA_LLEGADA_TEO']):
                return 'SIN DATO', 0
            try:
                h_real = pd.to_datetime(str(row['HORA LLEGADA DESTINO FINAL'])).time()
                h_teo = pd.to_datetime(str(row['HORA_LLEGADA_TEO'])).time()
                m_real = h_real.hour * 60 + h_real.minute
                m_teo = h_teo.hour * 60 + h_teo.minute
                diff = m_real - m_teo
                
                # Tolerancia: Llegada a tiempo o anticipada es ON TIME, retraso <= 15 min es ON TIME
                if diff <= 15:
                    return 'ON TIME', max(0, diff)
                else:
                    return 'LLEGADA TARDÍA', diff
            except:
                return 'SIN DATO', 0

        res_salida = df_proc.apply(evaluar_salida, axis=1)
        df_proc['ESTADO_SALIDA'] = [r[0] for r in res_salida]
        df_proc['RETRASO_SALIDA_MIN'] = [r[1] for r in res_salida]

        res_llegada = df_proc.apply(evaluar_llegada, axis=1)
        df_proc['ESTADO_LLEGADA'] = [r[0] for r in res_llegada]
        df_proc['RETRASO_LLEGADA_MIN'] = [r[1] for r in res_llegada]

        # ---------------------------------------------------------
        # FILTROS LATERALES DINÁMICOS
        # ---------------------------------------------------------
        st.sidebar.header("🔍 Filtros Operativos")
        
        # Filtro de Fechas
        min_date = df_proc['FECHA_SALIDA_DT'].min()
        max_date = df_proc['FECHA_SALIDA_DT'].max()
        
        if pd.notna(min_date) and pd.notna(max_date):
            rango_fechas = st.sidebar.date_input("Rango de Fechas", value=(min_date, max_date))
            if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
                df_filtered = df_proc[(df_proc['FECHA_SALIDA_DT'] >= pd.to_datetime(rango_fechas[0])) & 
                                      (df_proc['FECHA_SALIDA_DT'] <= pd.to_datetime(rango_fechas[1]))]
            else:
                df_filtered = df_proc.copy()
        else:
            df_filtered = df_proc.copy()

        # Filtro por Origen
        lista_origenes = sorted(list(df_filtered['ORIGEN_NORM'].dropna().unique()))
        origen_sel = st.sidebar.multiselect("Plaza Origen", options=lista_origenes, default=lista_origenes)
        if origen_sel:
            df_filtered = df_filtered[df_filtered['ORIGEN_NORM'].isin(origen_sel)]

        # Filtro por Destino
        lista_destinos = sorted(list(df_filtered['DESTINO_NORM'].dropna().unique()))
        destino_sel = st.sidebar.multiselect("Plaza Destino", options=lista_destinos, default=lista_destinos)
        if destino_sel:
            df_filtered = df_filtered[df_filtered['DESTINO_NORM'].isin(destino_sel)]

        # ---------------------------------------------------------
        # TARJETAS DE INDICADORES GENERALES (KPIs)
        # ---------------------------------------------------------
        total_viajes = len(df_filtered)
        salidas_ontime = (df_filtered['ESTADO_SALIDA'] == 'ON TIME').sum()
        llegadas_ontime = (df_filtered['ESTADO_LLEGADA'] == 'ON TIME').sum()
        
        pct_salidas = (salidas_ontime / total_viajes * 100) if total_viajes > 0 else 0
        pct_llegadas = (llegadas_ontime / total_viajes * 100) if total_viajes > 0 else 0
        pct_general = ((salidas_ontime + llegadas_ontime) / (total_viajes * 2) * 100) if total_viajes > 0 else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Viajes Evaluados", f"{total_viajes:,}")
        col2.metric("Cumplimiento Despacho (Salidas)", f"{pct_salidas:.1f}%")
        col3.metric("Cumplimiento Arribo (Llegadas)", f"{pct_llegadas:.1f}%")
        col4.metric("On-Time General de Red", f"{pct_general:.1f}%")

        st.markdown("---")

        # ---------------------------------------------------------
        # DETALLE DRILL-DOWN POR INDICADOR (RESPUESTA A TU PREGUNTA)
        # ---------------------------------------------------------
        st.subheader("📋 Detalle Específico de Registros por Tipo de Desempeño")
        
        filtro_detalle = st.selectbox(
            "Selecciona la categoría que deseas auditar a detalle:",
            ["Todas las Salidas Tardías", "Todas las Llegadas Tardías", "Viajes Completos ON TIME", "Ver Todo el Universo Seleccionado"]
        )

        if filtro_detalle == "Todas las Salidas Tardías":
            df_sub_detalle = df_filtered[df_filtered['ESTADO_SALIDA'] == 'SALIDA TARDÍA']
        elif filtro_detalle == "Todas las Llegadas Tardías":
            df_sub_detalle = df_filtered[df_filtered['ESTADO_LLEGADA'] == 'LLEGADA TARDÍA']
        elif filtro_detalle == "Viajes Completos ON TIME":
            df_sub_detalle = df_filtered[(df_filtered['ESTADO_SALIDA'] == 'ON TIME') & (df_filtered['ESTADO_LLEGADA'] == 'ON TIME')]
        else:
            df_sub_detalle = df_filtered.copy()

        cols_mostrar = ['ORIGEN_NORM', 'DESTINO_NORM', 'FECHA SALIDA', 'OPERADOR', 'NO.ECO', 'FOLIO', 'ESTADO_SALIDA', 'RETRASO_SALIDA_MIN', 'ESTADO_LLEGADA', 'RETRASO_LLEGADA_MIN', 'COMENTARIOS/OBSERVACIONES']
        cols_existentes = [c for c in cols_mostrar if c in df_sub_detalle.columns]

        with st.expander(f"🔍 Ver registros filtrados ({len(df_sub_detalle)} registros)", expanded=True):
            st.dataframe(df_sub_detalle[cols_existentes], use_container_width=True)

        st.markdown("---")

        # ---------------------------------------------------------
        # APERTURA DE EFICIENCIA (SALIDAS Y LLEGADAS) POR CEDIS ORIGEN Y DESTINOS
        # ---------------------------------------------------------
        st.subheader("🏢 Apertura de Eficiencia (Salidas vs Llegadas) por CEDIS Origen")

        # Agrupación por Origen
        df_cedis = df_filtered.groupby('ORIGEN_NORM').agg(
            Total=('FOLIO', 'count'),
            Salidas_OnTime=('ESTADO_SALIDA', lambda x: (x == 'ON TIME').sum()),
            Llegadas_OnTime=('ESTADO_LLEGADA', lambda x: (x == 'ON TIME').sum())
        ).reset_index()

        df_cedis['% Eficiencia Salida'] = (df_cedis['Salidas_OnTime'] / df_cedis['Total']) * 100
        df_cedis['% Eficiencia Llegada'] = (df_cedis['Llegadas_OnTime'] / df_cedis['Total']) * 100

        # Formato para el gráfico comparativo
        df_chart_cedis = pd.melt(
            df_cedis, 
            id_vars=['ORIGEN_NORM'], 
            value_vars=['% Eficiencia Salida', '% Eficiencia Llegada'],
            var_name='Tipo Metrica', 
            value_name='Porcentaje %'
        )

        fig_cedis = px.bar(
            df_chart_cedis,
            x='ORIGEN_NORM',
            y='Porcentaje %',
            color='Tipo Metrica',
            barmode='group',
            text_auto='.1f',
            title="Comparativo de Eficiencia: Despacho (Salida) vs Arribo (Llegada) por Plaza Origen",
            labels={'ORIGEN_NORM': 'CEDIS Origen'},
            color_discrete_map={'% Eficiencia Salida': '#1f77b4', '% Eficiencia Llegada': '#2ca02c'}
        )
        st.plotly_chart(fig_cedis, use_container_width=True)

        # Agrupación por Destino
        st.subheader("🎯 Apertura de Eficiencia (Salidas vs Llegadas) por Destinos")
        
        df_dest = df_filtered.groupby('DESTINO_NORM').agg(
            Total=('FOLIO', 'count'),
            Salidas_OnTime=('ESTADO_SALIDA', lambda x: (x == 'ON TIME').sum()),
            Llegadas_OnTime=('ESTADO_LLEGADA', lambda x: (x == 'ON TIME').sum())
        ).reset_index()

        df_dest['% Eficiencia Salida'] = (df_dest['Salidas_OnTime'] / df_dest['Total']) * 100
        df_dest['% Eficiencia Llegada'] = (df_dest['Llegadas_OnTime'] / df_dest['Total']) * 100

        df_chart_dest = pd.melt(
            df_dest, 
            id_vars=['DESTINO_NORM'], 
            value_vars=['% Eficiencia Salida', '% Eficiencia Llegada'],
            var_name='Tipo Metrica', 
            value_name='Porcentaje %'
        )

        fig_dest = px.bar(
            df_chart_dest,
            x='DESTINO_NORM',
            y='Porcentaje %',
            color='Tipo Metrica',
            barmode='group',
            text_auto='.1f',
            title="Comparativo de Eficiencia por Plaza Destino",
            labels={'DESTINO_NORM': 'Plaza Destino'},
            color_discrete_map={'% Eficiencia Salida': '#1f77b4', '% Eficiencia Llegada': '#2ca02c'}
        )
        st.plotly_chart(fig_dest, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Error al procesar el archivo: {str(e)}")
