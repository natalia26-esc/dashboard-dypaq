import streamlit as st
import pandas as pd
import plotly.express as px
import datetime

# ---------------------------------------------------------
# 1. FUNCIONES AUXILIARES
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
# CONFIGURACIÓN DE PÁGINA
# ---------------------------------------------------------
st.set_page_config(
    page_title="Torre de Control DYPAQ - Circuitos",
    layout="wide",
    page_icon="📊"
)

st.title("📊 Torre de Control de Circuitos Nacionales | DYPAQ")
st.markdown("### *Indicadores de Rendimiento de Red: Análisis de Despacho, Arribo e Incidencias*")
st.markdown("---")

uploaded_file = st.file_uploader("📂 Cargar Matriz Unificada de Control de Vehículos", type=["xlsx"])

if uploaded_file is not None:
    try:
        excel_obj = pd.ExcelFile(uploaded_file)
        
        # 1. LECTURA Y NORMALIZACIÓN DE HORARIOS ESTABLECIDOS
        df_horarios = pd.read_excel(uploaded_file, sheet_name='HORARIOS ESTABLECIDOS')
        df_horarios.columns = df_horarios.columns.astype(str).str.strip().str.upper()
        
        col_h_sal = [c for c in df_horarios.columns if 'SALIDA' in c][0]
        col_h_lleg = [c for c in df_horarios.columns if 'LLEGADA' in c or 'FINAL' in c][0]
        
        df_horarios['ORIGEN'] = df_horarios['ORIGEN'].apply(normalizar_texto)
        df_horarios['DESTINO'] = df_horarios['DESTINO'].apply(normalizar_texto)
        df_horarios['RUTA_KEY'] = df_horarios['ORIGEN'].str.replace(" ", "") + "_" + df_horarios['DESTINO'].str.replace(" ", "")
        
        df_horarios_clean = df_horarios.drop_duplicates(subset=['RUTA_KEY'])[['RUTA_KEY', col_h_sal, col_h_lleg]].copy()
        df_horarios_clean.columns = ['RUTA_KEY', 'TEORICA_SALIDA', 'TEORICA_LLEGADA']

        # 2. CONSOLIDACIÓN DE HOJAS DE PLAZAS
        hojas_excluidas = ['HORARIOS ESTABLECIDOS', 'COMENTARIOS', 'NOTAS', 'SHEET1', 'DASHBOARD', 'PORTADA']
        hojas_plazas = [h for h in excel_obj.sheet_names if h.upper() not in hojas_excluidas]
        
        listado = []
        for plaza in hojas_plazas:
            df_p = pd.read_excel(uploaded_file, sheet_name=plaza)
            df_p.columns = df_p.columns.astype(str).str.strip().str.upper()
            
            if 'ORIGEN' in df_p.columns and 'DESTINO' in df_p.columns:
                columnas_fecha = [c for c in df_p.columns if 'FECHA' in c]
                col_fecha_real = columnas_fecha[0] if columnas_fecha else None
                columnas_comentarios = [c for c in df_p.columns if 'COMENT' in c or 'OBSERV' in c or 'ESTATUS' in c]
                col_comentarios_real = columnas_comentarios[0] if columnas_comentarios else None
                
                if not col_fecha_real: continue
                
                columnas_a_copy = {
                    'ORIGEN': df_p['ORIGEN'],
                    'DESTINO': df_p['DESTINO'],
                    'HORA SALIDA REAL': df_p['HORA SALIDA'] if 'HORA SALIDA' in df_p.columns else None,
                    'HORA LLEGADA REAL': df_p['HORA LLEGADA DESTINO FINAL'] if 'HORA LLEGADA DESTINO FINAL' in df_p.columns else None,
                    'OPERADOR': df_p['OPERADOR'] if 'OPERADOR' in df_p.columns else (df_p['CHOFER'] if 'CHOFER' in df_p.columns else None),
                    'FOLIO': df_p['FOLIO'] if 'FOLIO' in df_p.columns else None,
                    'NO.ECO': df_p['NO.ECO'] if 'NO.ECO' in df_p.columns else None,
                    'FECHA_SISTEMA': df_p[col_fecha_real],
                    'COMENTARIOS_SISTEMA': df_p[col_comentarios_real] if col_comentarios_real else "SIN OBSERVACIONES"
                }
                df_filtrado_columnas = pd.DataFrame(columnas_a_copy)
                df_filtrado_columnas['PLAZA_HOJA'] = plaza
                listado.append(df_filtrado_columnas.dropna(subset=['ORIGEN', 'DESTINO']))
                
        df_master = pd.concat(listado, ignore_index=True)
        
        # HOMOLOGACIÓN DE TEXTO
        for col in ['ORIGEN', 'DESTINO']:
            df_master[col] = df_master[col].apply(normalizar_texto)

        # PARSEO DE FECHAS SEGURO (CORRECCIÓN AÑO 2026 SIN ERRORES DE REEMPLAZO)
        df_master['FECHA_DT'] = pd.to_datetime(df_master['FECHA_SISTEMA'], errors='coerce')
        filas_na = df_master['FECHA_DT'].isna()
        if filas_na.any():
            df_master.loc[filas_na, 'FECHA_DT'] = pd.to_datetime(df_master.loc[filas_na, 'FECHA_SISTEMA'], dayfirst=True, errors='coerce')
        
        df_master = df_master.dropna(subset=['FECHA_DT'])
        
        # Ajuste de fechas truncadas a año 2026
        df_master.loc[df_master['FECHA_DT'].dt.year < 2000, 'FECHA_DT'] += pd.offsets.DateOffset(years=2000)
        df_master.loc[df_master['FECHA_DT'].dt.year != 2026, 'FECHA_DT'] = df_master['FECHA_DT'].apply(
            lambda d: pd.Timestamp(year=2026, month=d.month, day=d.day) if not (d.month == 2 and d.day == 29) else pd.Timestamp(year=2026, month=2, day=28)
        )

        # Días y Meses en español
        dias_espanol = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        df_master['Dia_Semana_Num'] = df_master['FECHA_DT'].dt.dayofweek
        df_master['Día de la Semana'] = df_master['Dia_Semana_Num'].map(dias_espanol)
        
        meses_espanol = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
            7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        df_master['Mes_Num'] = df_master['FECHA_DT'].dt.month
        df_master['Mes'] = df_master['Mes_Num'].map(meses_espanol)

        # CRUCE CON HORARIOS ESTABLECIDOS
        df_master['RUTA_KEY'] = df_master['ORIGEN'].str.replace(" ", "") + "_" + df_master['DESTINO'].str.replace(" ", "")
        df_unificado = pd.merge(df_master, df_horarios_clean, on='RUTA_KEY', how='left')

        # EVALUACIÓN DE TIEMPO (TOLERANCIA EXACTA: 15 MINUTOS)
        def parse_horario_flexible(h_val):
            if pd.isna(h_val) or str(h_val).strip() == "" or str(h_val).lower() in ["nan", "none", "pendiente"]:
                return None
            try:
                h_str = str(h_val).strip().upper()
                if 'AM' in h_str or 'PM' in h_str:
                    return pd.to_datetime(h_str, format='%I:%M%p', errors='coerce').time()
                return pd.to_datetime(h_str, errors='coerce').time()
            except:
                return None

        def evaluar_tiempo_absoluto(h_real, h_teorica):
            t_real = parse_horario_flexible(h_real)
            t_teo = parse_horario_flexible(h_teorica)
            if not t_real: return None, "Pendiente / Sin Captura"
            if not t_teo: return None, "Sin Horario Base"
            
            min_real = t_real.hour * 60 + t_real.minute
            min_teo = t_teo.hour * 60 + t_teo.minute
            dif = min_real - min_teo
            
            if dif < -720: dif += 1440
            if dif > 720: dif -= 1440
            
            # Regla de tolerancia: <= 15 minutos de retraso se considera On Time
            if dif > 15: return dif, "Demorado"
            else: return dif, "On Time"

        res_salida = df_unificado.apply(lambda r: evaluar_tiempo_absoluto(r['HORA SALIDA REAL'], r['TEORICA_SALIDA']), axis=1)
        df_unificado['MINUTOS_DIF_SALIDA'] = [x[0] for x in res_salida]
        df_unificado['ESTATUS_SALIDA'] = [x[1] for x in res_salida]

        res_llegada = df_unificado.apply(lambda r: evaluar_tiempo_absoluto(r['HORA LLEGADA REAL'], r['TEORICA_LLEGADA']), axis=1)
        df_unificado['MINUTOS_DIF_LLEGADA'] = [x[0] for x in res_llegada]
        df_unificado['ESTATUS_LLEGADA'] = [x[1] for x in res_llegada]

        # ---------------------------------------------------------
        # FILTROS LATERALES
        # ---------------------------------------------------------
        st.sidebar.header("🕹️ Filtros de Control")
        
        # Filtro por Mes
        meses_disponibles = ['Todos'] + [meses_espanol[m] for m in sorted(df_unificado['Mes_Num'].unique())]
        mes_sel = st.sidebar.selectbox("Filtrar por Mes", meses_disponibles)
        
        df_f_mes = df_unificado[df_unificado['Mes'] == mes_sel] if mes_sel != 'Todos' else df_unificado.copy()

        # Filtro por Rango de Fechas
        min_date = df_f_mes['FECHA_DT'].min().date()
        max_date = df_f_mes['FECHA_DT'].max().date()
        
        rango_fechas = st.sidebar.date_input("Rango de Fechas Exacto", [min_date, max_date])
        
        if isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 2:
            df_f_fecha = df_f_mes[(df_f_mes['FECHA_DT'].dt.date >= rango_fechas[0]) & (df_f_mes['FECHA_DT'].dt.date <= rango_fechas[1])]
        elif isinstance(rango_fechas, (list, tuple)) and len(rango_fechas) == 1:
            df_f_fecha = df_f_mes[df_f_mes['FECHA_DT'].dt.date == rango_fechas[0]]
        else:
            df_f_fecha = df_f_mes.copy()

        # Filtro por Plaza Origen
        origen_disp = sorted(df_f_fecha['ORIGEN'].unique().tolist())
        origen_sel = st.sidebar.multiselect("Plaza Origen", origen_disp, default=origen_disp)
        
        df_f_origen = df_f_fecha[df_f_fecha['ORIGEN'].isin(origen_sel)]
        
        # Filtro por Plaza Destino (Filtrado dinámico según Origen seleccionado)
        destino_disp = sorted(df_f_origen['DESTINO'].unique().tolist())
        destino_sel = st.sidebar.multiselect("Plaza Destino", destino_disp, default=destino_disp)
        
        df_filtrado = df_f_origen[df_f_origen['DESTINO'].isin(destino_sel)]

        df_sal_v = df_filtrado[df_filtrado['ESTATUS_SALIDA'].isin(['On Time', 'Demorado'])]
        df_lleg_v = df_filtrado[df_filtrado['ESTATUS_LLEGADA'].isin(['On Time', 'Demorado'])]
        
        # ---------------------------------------------------------
        # RESUMEN EJECUTIVO (KPIs DIRECTIVOS)
        # ---------------------------------------------------------
        st.markdown("#### 📊 Resumen Ejecutivo de Desempeño")
        k1, k2, k3 = st.columns(3)
        tot_sal_ok = (df_sal_v['ESTATUS_SALIDA'] == 'On Time').sum()
        tot_lleg_ok = (df_lleg_v['ESTATUS_LLEGADA'] == 'On Time').sum()
        
        pct_sal = (tot_sal_ok / len(df_sal_v) * 100) if len(df_sal_v) > 0 else 0
        pct_lleg = (tot_lleg_ok / len(df_lleg_v) * 100) if len(df_lleg_v) > 0 else 0
        
        total_eventos_validos = len(df_sal_v) + len(df_lleg_v)
        total_on_time_conjunto = tot_sal_ok + tot_lleg_ok
        pct_conjunto = (total_on_time_conjunto / total_eventos_validos * 100) if total_eventos_validos > 0 else 0
        
        k1.metric("On-Time Despacho (Salidas)", f"{pct_sal:.1f}%", f"{tot_sal_ok} de {len(df_sal_v)} a tiempo (Tol. 15m)")
        k2.metric("On-Time Cumplimiento (Llegadas)", f"{pct_lleg:.1f}%", f"{tot_lleg_ok} de {len(df_lleg_v)} a tiempo (Tol. 15m)")
        k3.metric("🎯 On-Time General de la Red", f"{pct_conjunto:.1f}%", "Eficiencia integrada (Salidas + Llegadas)")
        
        st.write("") 
        k_time1, k_time2 = st.columns(2)
        
        avg_sal_min = df_sal_v[df_sal_v['MINUTOS_DIF_SALIDA'] > 0]['MINUTOS_DIF_SALIDA'].mean()
        txt_avg_sal = formatear_minutos_a_string(avg_sal_min) if pd.notna(avg_sal_min) else "0 min"
        k_time1.metric("Retraso Promedio en Salida", txt_avg_sal, "Desviación andén origen (Solo retrasos)")
        
        avg_lleg_min = df_lleg_v[df_lleg_v['MINUTOS_DIF_LLEGADA'] > 0]['MINUTOS_DIF_LLEGADA'].mean()
        txt_avg_lleg = formatear_minutos_a_string(avg_lleg_min) if pd.notna(avg_lleg_min) else "0 min"
        k_time2.metric("Retraso Promedio en Arribo (Llegadas)", txt_avg_lleg, "Desviación destino final (Solo retrasos)")
        
        st.markdown("---")

        # ---------------------------------------------------------
        # DETALLE DRILL-DOWN POR INDICADOR
        # ---------------------------------------------------------
        st.subheader("📋 Auditoría Detallada de Registros")
        
        filtro_detalle = st.selectbox(
            "Selecciona la categoría que deseas auditar a detalle:",
            ["Todas las Salidas Tardías", "Todas las Llegadas Tardías", "Viajes Completos ON TIME", "Ver Todo el Universo Seleccionado"]
        )

        if filtro_detalle == "Todas las Salidas Tardías":
            df_sub_detalle = df_filtrado[df_filtrado['ESTATUS_SALIDA'] == 'Demorado']
        elif filtro_detalle == "Todas las Llegadas Tardías":
            df_sub_detalle = df_filtrado[df_filtrado['ESTATUS_LLEGADA'] == 'Demorado']
        elif filtro_detalle == "Viajes Completos ON TIME":
            df_sub_detalle = df_filtrado[(df_filtrado['ESTATUS_SALIDA'] == 'On Time') & (df_filtrado['ESTATUS_LLEGADA'] == 'On Time')]
        else:
            df_sub_detalle = df_filtrado.copy()

        df_sub_detalle_tabla = pd.DataFrame()
        if len(df_sub_detalle) > 0:
            df_sub_detalle_tabla['Fecha'] = df_sub_detalle['FECHA_DT'].dt.strftime('%Y-%m-%d')
            df_sub_detalle_tabla['Origen'] = df_sub_detalle['ORIGEN']
            df_sub_detalle_tabla['Destino'] = df_sub_detalle['DESTINO']
            df_sub_detalle_tabla['Operador'] = df_sub_detalle['OPERADOR'].fillna("N/E")
            df_sub_detalle_tabla['No. Eco'] = df_sub_detalle['NO.ECO'].fillna("N/E")
            df_sub_detalle_tabla['Folio'] = df_sub_detalle['FOLIO'].fillna("N/A")
            df_sub_detalle_tabla['Hora Salida Real'] = df_sub_detalle['HORA SALIDA REAL']
            df_sub_detalle_tabla['Estatus Salida'] = df_sub_detalle['ESTATUS_SALIDA']
            df_sub_detalle_tabla['Hora Llegada Real'] = df_sub_detalle['HORA LLEGADA REAL']
            df_sub_detalle_tabla['Estatus Llegada'] = df_sub_detalle['ESTATUS_LLEGADA']
            df_sub_detalle_tabla['Observaciones'] = df_sub_detalle['COMENTARIOS_SISTEMA']

        with st.expander(f"🔍 Ver registros filtrados ({len(df_sub_detalle_tabla)} registros)", expanded=True):
            st.dataframe(df_sub_detalle_tabla, use_container_width=True, hide_index=True)

        st.markdown("---")
        
        # ---------------------------------------------------------
        # PESTAÑAS PRINCIPALES
        # ---------------------------------------------------------
        tab_volumen, tab_rutas, tab_operadores, tab_incidencias = st.tabs([
            "🌐 Análisis por Periodo y Día", "🚨 Análisis de Rutas Críticas", "👤 Confiabilidad de Operadores", "💬 Bitácora de Incidencias"
        ])
        
        with tab_volumen:
            st.subheader("Evaluación Temporal de Controles")
            c_g1, c_g2 = st.columns(2)
            with c_g1:
                st.markdown("**Volumen de Circuitos por Estatus Mensual**")
                if len(df_sal_v) > 0:
                    fig_m_sal = px.histogram(df_sal_v, x='Mes', color='ESTATUS_SALIDA', barmode='group',
                                             labels={'count': 'Viajes', 'Mes': 'Mes'},
                                             color_discrete_map={'On Time':'#2ca02c', 'Demorado':'#d62728'})
                    fig_m_sal.update_layout(yaxis_title="Cantidad de Viajes")
                    st.plotly_chart(fig_m_sal, use_container_width=True)
            with c_g2:
                st.markdown("**Análisis Crítico por Día de la Semana**")
                if len(df_sal_v) > 0:
                    df_dias = df_sal_v.sort_values('Dia_Semana_Num')
                    fig_d_sal = px.histogram(df_dias, x='Día de la Semana', color='ESTATUS_SALIDA', barmode='group',
                                             color_discrete_map={'On Time':'#2ca02c', 'Demorado':'#d62728'})
                    fig_d_sal.update_layout(yaxis_title="Cantidad de Viajes")
                    st.plotly_chart(fig_d_sal, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### Apertura de Eficiencia (Salidas vs Llegadas) por CEDIS Origen y Destinos")
            
            df_perf_origen = df_filtrado.groupby('ORIGEN').agg(
                Total_Salidas=('ESTATUS_SALIDA', lambda x: x.isin(['On Time', 'Demorado']).sum()),
                Salidas_OnTime=('ESTATUS_SALIDA', lambda x: (x == 'On Time').sum()),
                Total_Llegadas=('ESTATUS_LLEGADA', lambda x: x.isin(['On Time', 'Demorado']).sum()),
                Llegadas_OnTime=('ESTATUS_LLEGADA', lambda x: (x == 'On Time').sum())
            ).reset_index()

            df_perf_origen['% On-Time Salida'] = (df_perf_origen['Salidas_OnTime'] / df_perf_origen['Total_Salidas'] * 100).fillna(0)
            df_perf_origen['% On-Time Llegada'] = (df_perf_origen['Llegadas_OnTime'] / df_perf_origen['Total_Llegadas'] * 100).fillna(0)

            df_chart_cedis = pd.melt(
                df_perf_origen, 
                id_vars=['ORIGEN'], 
                value_vars=['% On-Time Salida', '% On-Time Llegada'],
                var_name='Métrica', 
                value_name='% Eficiencia'
            )

            fig_bar_p = px.bar(
                df_chart_cedis, 
                x='ORIGEN', 
                y='% Eficiencia', 
                color='Métrica', 
                barmode='group',
                text='% Eficiencia',
                color_discrete_map={'% On-Time Salida': '#1f77b4', '% On-Time Llegada': '#2ca02c'}
            )
            fig_bar_p.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            st.plotly_chart(fig_bar_p, use_container_width=True)

            df_destinos_perf = df_filtrado.groupby(['ORIGEN', 'DESTINO']).agg(
                Total_Viajes=('FOLIO', 'count'),
                Salidas_OnTime=('ESTATUS_SALIDA', lambda x: (x == 'On Time').sum()),
                Salidas_Eval=('ESTATUS_SALIDA', lambda x: x.isin(['On Time', 'Demorado']).sum()),
                Llegadas_OnTime=('ESTATUS_LLEGADA', lambda x: (x == 'On Time').sum()),
                Llegadas_Eval=('ESTATUS_LLEGADA', lambda x: x.isin(['On Time', 'Demorado']).sum())
            ).reset_index()
            
            df_destinos_perf['% Eficiencia Salida'] = (df_destinos_perf['Salidas_OnTime'] / df_destinos_perf['Salidas_Eval'] * 100).fillna(0).round(1)
            df_destinos_perf['% Eficiencia Llegada'] = (df_destinos_perf['Llegadas_OnTime'] / df_destinos_perf['Llegadas_Eval'] * 100).fillna(0).round(1)
            
            st.markdown("**Detalle de Cumplimiento por Tramo Origen-Destino**")
            st.dataframe(df_destinos_perf[['ORIGEN', 'DESTINO', 'Total_Viajes', '% Eficiencia Salida', '% Eficiencia Llegada']].sort_values(by='% Eficiencia Salida', ascending=False), use_container_width=True, hide_index=True)

        with tab_rutas:
            st.subheader("Tramos con Mayor Desviación en Horas y Minutos")
            col_r1, col_r2 = st.columns(2)
            df_dem_sal = df_sal_v[df_sal_v['MINUTOS_DIF_SALIDA'] > 15]
            df_dem_lleg = df_lleg_v[df_lleg_v['MINUTOS_DIF_LLEGADA'] > 15]
            
            with col_r1:
                st.markdown("📋 **Desviaciones en Despacho (SALIDAS)**")
                if len(df_dem_sal) > 0:
                    rutas_sal = df_dem_sal.groupby(['ORIGEN', 'DESTINO']).agg(Viajes_Demorados=('FOLIO', 'count'), Promedio_Minutos=('MINUTOS_DIF_SALIDA', 'mean'), Maximo_Minutos=('MINUTOS_DIF_SALIDA', 'max')).reset_index().sort_values(by='Viajes_Demorados', ascending=False)
                    rutas_sal['Retraso Prom'] = rutas_sal['Promedio_Minutos'].apply(formatear_minutos_a_string)
                    rutas_sal['Retraso Max'] = rutas_sal['Maximo_Minutos'].apply(formatear_minutos_a_string)
                    st.dataframe(rutas_sal[['ORIGEN', 'DESTINO', 'Viajes_Demorados', 'Retraso Prom', 'Retraso Max']], use_container_width=True, hide_index=True)
                else:
                    st.success("Sin demoras fuera de la tolerancia de 15 min en salidas.")
            with col_r2:
                st.markdown("📋 **Desviaciones en Destino Final (LLEGADAS)**")
                if len(df_dem_lleg) > 0:
                    rutas_lleg = df_dem_lleg.groupby(['ORIGEN', 'DESTINO']).agg(Viajes_Demorados=('FOLIO', 'count'), Promedio_Minutos=('MINUTOS_DIF_LLEGADA', 'mean'), Maximo_Minutos=('MINUTOS_DIF_LLEGADA', 'max')).reset_index().sort_values(by='Viajes_Demorados', ascending=False)
                    rutas_lleg['Retraso Prom'] = rutas_lleg['Promedio_Minutos'].apply(formatear_minutos_a_string)
                    rutas_lleg['Retraso Max'] = rutas_lleg['Maximo_Minutos'].apply(formatear_minutos_a_string)
                    st.dataframe(rutas_lleg[['ORIGEN', 'DESTINO', 'Viajes_Demorados', 'Retraso Prom', 'Retraso Max']], use_container_width=True, hide_index=True)
                else:
                    st.success("Sin demoras fuera de la tolerancia de 15 min en arribos.")
            
            st.markdown("---")
            st.markdown("### 📅 Análisis de Frecuencia y Fechas: ¿Cuándo fallan las Salidas Críticas?")
            if len(df_dem_sal) > 0:
                df_dem_sal['Fecha_Corta'] = df_dem_sal['FECHA_DT'].dt.strftime('%Y-%m-%d')
                df_frec_fechas = df_dem_sal.groupby(['ORIGEN', 'DESTINO', 'Fecha_Corta', 'Día de la Semana']).agg(Viajes_Demorados=('FOLIO', 'count'), Retraso_Promedio=('MINUTOS_DIF_SALIDA', 'mean')).reset_index()
                df_frec_fechas['Retraso_Promedio'] = df_frec_fechas['Retraso_Promedio'].apply(formatear_minutos_a_string)
                df_reporte_frecuencias = df_frec_fechas[['ORIGEN', 'DESTINO', 'Fecha_Corta', 'Día de la Semana', 'Viajes_Demorados', 'Retraso_Promedio']].copy()
                df_reporte_frecuencias.columns = ['Origen', 'Destino', 'Fecha del Retraso', 'Día de la Semana', 'Viajes Demorados', 'Retraso Promedio']
                st.dataframe(df_reporte_frecuencias.sort_values(by='Fecha del Retraso'), use_container_width=True, hide_index=True)

        with tab_operadores:
            st.subheader("Matriz de Confiabilidad Unificada por Operador")
            if len(df_filtrado) > 0:
                op_stats = df_filtrado.groupby(['OPERADOR']).agg(
                    Total_Viajes=('FOLIO', 'count'),
                    Salidas_Evaluadas=('ESTATUS_SALIDA', lambda x: x.isin(['On Time', 'Demorado']).sum()),
                    Salidas_On_Time=('ESTATUS_SALIDA', lambda x: (x == 'On Time').sum()),
                    Llegadas_Evaluadas=('ESTATUS_LLEGADA', lambda x: x.isin(['On Time', 'Demorado']).sum()),
                    Llegadas_On_Time=('ESTATUS_LLEGADA', lambda x: (x == 'On Time').sum())
                ).reset_index()
                
                op_stats['% On-Time Salida'] = (op_stats['Salidas_On_Time'] / op_stats['Salidas_Evaluadas'] * 100).fillna(0)
                op_stats['% On-Time Llegada'] = (op_stats['Llegadas_On_Time'] / op_stats['Llegadas_Evaluadas'] * 100).fillna(0)
                op_stats['% On-Time General'] = (op_stats['% On-Time Salida'] + op_stats['% On-Time Llegada']) / 2
                op_reporte = op_stats[['OPERADOR', 'Total_Viajes', '% On-Time Salida', '% On-Time Llegada', '% On-Time General']].sort_values(by='% On-Time General', ascending=False)
                st.dataframe(op_reporte.style.format({'% On-Time Salida': '{:.1f}%', '% On-Time Llegada': '{:.1f}%', '% On-Time General': '{:.1f}%', 'Total_Viajes': '{:.0f}'}), use_container_width=True, hide_index=True)

        with tab_incidencias:
            st.subheader("Bitácora General de Incidencias Operativas")
            df_comentarios = df_filtrado[df_filtrado['COMENTARIOS_SISTEMA'].notna() & (df_filtrado['COMENTARIOS_SISTEMA'] != "") & (df_filtrado['COMENTARIOS_SISTEMA'] != "0") & (df_filtrado['COMENTARIOS_SISTEMA'] != 0)]
            df_inc_tabla = pd.DataFrame()
            if len(df_comentarios) > 0:
                df_inc_tabla['Fecha'] = df_comentarios['FECHA_DT'].dt.strftime('%Y-%m-%d')
                df_inc_tabla['Folio'] = df_comentarios['FOLIO'].fillna("N/A")
                df_inc_tabla['Origen'] = df_comentarios['ORIGEN']
                df_inc_tabla['Destino'] = df_comentarios['DESTINO']
                df_inc_tabla['Operador'] = df_comentarios['OPERADOR'].fillna("N/E")
                df_inc_tabla['Estatus Salida'] = df_comentarios['ESTATUS_SALIDA']
                df_inc_tabla['Estatus Llegada'] = df_comentarios['ESTATUS_LLEGADA']
                df_inc_tabla['Observaciones Registradas'] = df_comentarios['COMENTARIOS_SISTEMA']
            st.dataframe(df_inc_tabla, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error en el procesamiento de datos de la red: {e}")
else:
    st.info("💼 Por favor cargue la matriz de control para inicializar el análisis corporativo.")
