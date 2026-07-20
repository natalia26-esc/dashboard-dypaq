import streamlit as st
import pandas as pd
import plotly.express as px
import datetime

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA STREAMLIT
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
# FUNCIONES DE TIEMPO Y NORMALIZACIÓN
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
        ("VHS", "VILLAHERMOSA"), ("VSA", "VILLAHERMOSA"), ("VJS", "VILLAHERMOSA"), ("VIH", "VILLAHERMOSA"),
        ("TLC", "TOLUCA"), ("VER", "VERACRUZ"), ("CUN", "CANCUN"),
        ("TX", "TUXTLA"), ("TUXTLA GUTIERREZ", "TUXTLA")
    )
    for a, b in replacements:
        txt = txt.replace(a, b)
    return txt

# ---------------------------------------------------------
# CARGA Y LECTURA DE ARCHIVOS DE EXCEL
# ---------------------------------------------------------
uploaded_file = st.file_uploader("📂 Cargar Matriz Unificada de Control de Vehículos", type=["xlsx"])

if uploaded_file is not None:
    try:
        excel_obj = pd.ExcelFile(uploaded_file)
        sheet_names = excel_obj.sheet_names
        
        # 1. Cargar Horarios Establecidos
        if 'HORARIOS ESTABLECIDOS' in sheet_names:
            df_horarios = pd.read_excel(uploaded_file, sheet_name='HORARIOS ESTABLECIDOS')
        else:
            df_horarios = pd.read_excel(uploaded_file, sheet_name=0)
            
        df_horarios.columns = df_horarios.columns.astype(str).str.strip().str.upper()
        df_horarios['ORIGEN_NORM'] = df_horarios['ORIGEN'].apply(normalizar_texto)
        df_horarios['DESTINO_NORM'] = df_horarios['DESTINO'].apply(normalizar_texto)
        df_horarios['RUTA_KEY'] = df_horarios['ORIGEN_NORM'] + "-" + df_horarios['DESTINO_NORM']
        
        map_salida_teo = dict(zip(df_horarios['RUTA_KEY'], df_horarios['HORA SALIDA']))
        map_llegada_teo = dict(zip(df_horarios['RUTA_KEY'], df_horarios['HORA LLEGADA DESTINO FINAL']))

        # 2. Cargar Hojas de Plazas
        hojas_excluidas = ['HORARIOS ESTABLECIDOS', 'COMENTARIOS', 'NOTAS', 'SHEET1', 'DASHBOARD', 'PORTADA']
        plazas_sheets = [s for s in sheet_names if s.upper() not in hojas_excluidas]
        
        df_list = []
        for sheet in plazas_sheets:
            df_temp = pd.read_excel(uploaded_file, sheet_name=sheet)
            df_temp.columns = df_temp.columns.astype(str).str.strip().str.upper()
            
            # Verificación de columnas requeridas
            if 'ORIGEN' in df_temp.columns and 'DESTINO' in df_temp.columns:
                df_unif = pd.DataFrame()
                df_unif['ORIGEN'] = df_temp['ORIGEN']
                df_unif['DESTINO'] = df_temp['DESTINO']
                df_unif['FECHA SALIDA'] = df_temp['FECHA SALIDA'] if 'FECHA SALIDA' in df_temp.columns else None
                df_unif['HORA SALIDA'] = df_temp['HORA SALIDA'] if 'HORA SALIDA' in df_temp.columns else None
                df_unif['FECHA LLEGADA DESTINO FINAL'] = df_temp['FECHA LLEGADA DESTINO FINAL'] if 'FECHA LLEGADA DESTINO FINAL' in df_temp.columns else None
                df_unif['HORA LLEGADA DESTINO FINAL'] = df_temp['HORA LLEGADA DESTINO FINAL'] if 'HORA LLEGADA DESTINO FINAL' in df_temp.columns else None
                df_unif['OPERADOR'] = df_temp['OPERADOR'] if 'OPERADOR' in df_temp.columns else None
                df_unif['FOLIO'] = df_temp['FOLIO'] if 'FOLIO' in df_temp.columns else None
                df_unif['NO.ECO'] = df_temp['NO.ECO'] if 'NO.ECO' in df_temp.columns else None
                
                col_obs = 'COMENTARIOS/OBSERVACIONES' if 'COMENTARIOS/OBSERVACIONES' in df_temp.columns else (
                    'COMENTARIOS' if 'COMENTARIOS' in df_temp.columns else None
                )
                df_unif['OBSERVACIONES'] = df_temp[col_obs] if col_obs else "SIN OBSERVACIONES"
                df_unif['PLAZA_HOJA'] = sheet
                
                df_list.append(df_unif.dropna(subset=['ORIGEN', 'DESTINO']))

        df_proc = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()

        # ---------------------------------------------------------
        # NORMALIZACIÓN Y REGLAS DE NEGOCIO (TOLERANCIA 15 MIN)
        # ---------------------------------------------------------
        df_proc['ORIGEN_NORM'] = df_proc['ORIGEN'].apply(normalizar_texto)
        df_proc['DESTINO_NORM'] = df_proc['DESTINO'].apply(normalizar_texto)
        df_proc['RUTA_KEY'] = df_proc['ORIGEN_NORM'] + "-" + df_proc['DESTINO_NORM']

        df_proc['FECHA_SALIDA_DT'] = pd.to_datetime(df_proc['FECHA SALIDA'], errors='coerce')

        # Asignar horarios teóricos de ruta
        df_proc['HORA_SALIDA_TEO'] = df_proc['RUTA_KEY'].map(map_salida_teo)
        df_proc['HORA_LLEGADA_TEO'] = df_proc['RUTA_KEY'].map(map_llegada_teo)

        def parse_horario(h_val):
            if pd.isna(h_val) or str(h_val).strip() == "" or str(h_val).lower() in ["nan", "none", "pendiente"]:
                return None
            try:
                return pd.to_datetime(str(h_val).strip()).time()
            except:
                return None

        # Evaluador de Salida (Tolerancia +15 min)
        def evaluar_salida(row):
            t_real = parse_horario(row['HORA SALIDA'])
            t_teo = parse_horario(row['HORA_SALIDA_TEO'])
            if not t_real or not t_teo:
                return 'SIN DATO', 0
            
            m_real = t_real.hour * 60 + t_real.minute
            m_teo = t_teo.hour * 60 + t_teo.minute
            diff = m_real - m_teo
            
            if diff < -720: diff += 1440
            if diff > 720: diff -= 1440
            
            if diff <= 15:
                return 'ON TIME', max(0, diff)
            else:
                return 'SALIDA TARDÍA', diff

        # Evaluador de Llegada (Tolerancia +15 min)
        def evaluar_llegada(row):
            t_real = parse_horario(row['HORA LLEGADA DESTINO FINAL'])
            t_teo = parse_horario(row['HORA_LLEGADA_TEO'])
            if not t_real or not t_teo:
                return 'SIN DATO', 0
            
            m_real = t_real.hour * 60 + t_real.minute
            m_teo = t_teo.hour * 60 + t_teo.minute
            diff = m_real - m_teo
            
            if diff < -720: diff += 1440
            if diff > 720: diff -= 1440
            
            if diff <= 15:
                return 'ON TIME', max(0, diff)
            else:
                return 'LLEGADA TARDÍA', diff

        res_salida = df_proc.apply(evaluar_salida, axis=1)
        df_proc['ESTADO_SALIDA'] = [r[0] for r in res_salida]
        df_proc['RETRASO_SALIDA_MIN'] = [r[1] for r in res_salida]

        res_llegada = df_proc.apply(evaluar_llegada, axis=1)
        df_proc['ESTADO_LLEGADA'] = [r[0] for r in res_llegada]
        df_proc['RETRASO_LLEGADA_MIN'] = [r[1] for r in res_llegada]

        # ---------------------------------------------------------
        # FILTROS LATERALES
        # ---------------------------------------------------------
        st.sidebar.header("🔍 Filtros Operativos")
        
        min_date = df_proc['FECHA_SALIDA_DT'].dropna().min()
        max_date = df_proc['FECHA_SALIDA_DT'].dropna().max()
        
        if pd.notna(min_date) and pd.notna(max_date):
            rango_fechas = st.sidebar.date_input("Rango de Fechas", value=(min_date.date(), max_date.date()))
            if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
                df_filtered = df_proc[(df_proc['FECHA_SALIDA_DT'].dt.date >= rango_fechas[0]) & 
                                      (df_proc['FECHA_SALIDA_DT'].dt.date <= rango_fechas[1])]
            elif isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 1:
                df_filtered = df_proc[df_proc['FECHA_SALIDA_DT'].dt.date == rango_fechas[0]]
            else:
                df_filtered = df_proc.copy()
        else:
            df_filtered = df_proc.copy()

        # Filtro Origen
        lista_origenes = sorted(list(df_filtered['ORIGEN_NORM'].dropna().unique()))
        origen_sel = st.sidebar.multiselect("Plaza Origen", options=lista_origenes, default=lista_origenes)
        if origen_sel:
            df_filtered = df_filtered[df_filtered['ORIGEN_NORM'].isin(origen_sel)]

        # Filtro Destino
        lista_destinos = sorted(list(df_filtered['DESTINO_NORM'].dropna().unique()))
        destino_sel = st.sidebar.multiselect("Plaza Destino", options=lista_destinos, default=lista_destinos)
        if destino_sel:
            df_filtered = df_filtered[df_filtered['DESTINO_NORM'].isin(destino_sel)]

        # ---------------------------------------------------------
        # RESUMEN EJECUTIVO (KPIs)
        # ---------------------------------------------------------
        df_sal_eval = df_filtered[df_filtered['ESTADO_SALIDA'].isin(['ON TIME', 'SALIDA TARDÍA'])]
        df_lleg_eval = df_filtered[df_filtered['ESTADO_LLEGADA'].isin(['ON TIME', 'LLEGADA TARDÍA'])]

        tot_sal = len(df_sal_eval)
        tot_lleg = len(df_lleg_eval)

        salidas_ontime = (df_sal_eval['ESTADO_SALIDA'] == 'ON TIME').sum()
        llegadas_ontime = (df_lleg_eval['ESTADO_LLEGADA'] == 'ON TIME').sum()
        
        pct_salidas = (salidas_ontime / tot_sal * 100) if tot_sal > 0 else 0
        pct_llegadas = (llegadas_ontime / tot_lleg * 100) if tot_lleg > 0 else 0
        
        tot_conjunto = tot_sal + tot_lleg
        pct_general = ((salidas_ontime + llegadas_ontime) / tot_conjunto * 100) if tot_conjunto > 0 else 0

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Viajes Registrados", f"{len(df_filtered):,}")
        col2.metric("Despacho On-Time (Salidas)", f"{pct_salidas:.1f}%", f"{salidas_ontime} de {tot_sal} (Tol. 15m)")
        col3.metric("Arribo On-Time (Llegadas)", f"{pct_llegadas:.1f}%", f"{llegadas_ontime} de {tot_lleg} (Tol. 15m)")
        col4.metric("🎯 On-Time General de Red", f"{pct_general:.1f}%", "Eficiencia integrada")

        st.markdown("---")

        # ---------------------------------------------------------
        # AUDITORÍA DETALLADA (DRILL-DOWN)
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

        cols_mostrar = ['ORIGEN_NORM', 'DESTINO_NORM', 'FECHA SALIDA', 'HORA SALIDA', 'HORA LLEGADA DESTINO FINAL', 'OPERADOR', 'NO.ECO', 'FOLIO', 'ESTADO_SALIDA', 'RETRASO_SALIDA_MIN', 'ESTADO_LLEGADA', 'RETRASO_LLEGADA_MIN', 'OBSERVACIONES']

        with st.expander(f"🔍 Ver registros filtrados ({len(df_sub_detalle)} registros)", expanded=True):
            st.dataframe(df_sub_detalle[cols_mostrar], use_container_width=True)

        st.markdown("---")

        # ---------------------------------------------------------
        # APERTURA DUAL (SALIDA Y LLEGADA) POR CEDIS Y DESTINOS
        # ---------------------------------------------------------
        st.subheader("🏢 Apertura de Eficiencia (Salidas vs Llegadas) por CEDIS Origen")

        df_cedis = df_filtered.groupby('ORIGEN_NORM').agg(
            Total_Salidas=('ESTADO_SALIDA', lambda x: x.isin(['ON TIME', 'SALIDA TARDÍA']).sum()),
            Salidas_OnTime=('ESTADO_SALIDA', lambda x: (x == 'ON TIME').sum()),
            Total_Llegadas=('ESTADO_LLEGADA', lambda x: x.isin(['ON TIME', 'LLEGADA TARDÍA']).sum()),
            Llegadas_OnTime=('ESTADO_LLEGADA', lambda x: (x == 'ON TIME').sum())
        ).reset_index()

        df_cedis['% Eficiencia Salida'] = (df_cedis['Salidas_OnTime'] / df_cedis['Total_Salidas'] * 100).fillna(0)
        df_cedis['% Eficiencia Llegada'] = (df_cedis['Llegadas_OnTime'] / df_cedis['Total_Llegadas'] * 100).fillna(0)

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

        st.subheader("🎯 Apertura de Eficiencia (Salidas vs Llegadas) por Destinos")
        
        df_dest = df_filtered.groupby('DESTINO_NORM').agg(
            Total_Salidas=('ESTADO_SALIDA', lambda x: x.isin(['ON TIME', 'SALIDA TARDÍA']).sum()),
            Salidas_OnTime=('ESTADO_SALIDA', lambda x: (x == 'ON TIME').sum()),
            Total_Llegadas=('ESTADO_LLEGADA', lambda x: x.isin(['ON TIME', 'LLEGADA TARDÍA']).sum()),
            Llegadas_OnTime=('ESTADO_LLEGADA', lambda x: (x == 'ON TIME').sum())
        ).reset_index()

        df_dest['% Eficiencia Salida'] = (df_dest['Salidas_OnTime'] / df_dest['Total_Salidas'] * 100).fillna(0)
        df_dest['% Eficiencia Llegada'] = (df_dest['Llegadas_OnTime'] / df_dest['Total_Llegadas'] * 100).fillna(0)

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
else:
    st.info("💼 Por favor cargue la matriz de control para inicializar el análisis corporativo.")
