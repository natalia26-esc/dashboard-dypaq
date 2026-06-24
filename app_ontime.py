import streamlit as st
import pandas as pd
import plotly.express as px

# 1. FUNCIÓN GLOBAL DE FORMATO DE TIEMPO (Declarada al inicio para evitar NameError)
def formatear_minutos_a_string(minutos_totales):
    if pd.isna(minutos_totales) or minutos_totales <= 0:
        return "0 min"
    hrs = int(minutos_totales // 60)
    mins = int(minutos_totales % 60)
    if hrs > 0:
        return f"{hrs} hrs {mins} min" if mins > 0 else f"{hrs} hrs"
    return f"{mins} min"

# Configuración de página de Streamlit
st.set_page_config(page_title="Torre de Control DYPAQ - Circuitos", layout="wide", page_icon="📊")

st.title("📊 Torre de Control de Circuitos Nacionales | DYPAQ")
st.markdown("### *Indicadores de Rendimiento de Red: Análisis de Despacho, Arribo e Incidencias*")
st.markdown("---")

uploaded_file = st.file_uploader("📂 Cargar Matriz Unificada de Control de Vehículos", type=["xlsx"])

if uploaded_file is not None:
    try:
        excel_obj = pd.ExcelFile(uploaded_file)
        df_horarios = pd.read_excel(uploaded_file, sheet_name='HORARIOS ESTABLECIDOS')
        df_horarios.columns = df_horarios.columns.astype(str).str.strip().str.upper()
        
        hojas_excluidas = ['HORARIOS ESTABLECIDOS', 'COMENTARIOS', 'NOTAS', 'SHEET1']
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
                    'FECHA_SISTEMA': df_p[col_fecha_real],
                    'COMENTARIOS_SISTEMA': df_p[col_comentarios_real] if col_comentarios_real else "SIN OBSERVACIONES"
                }
                df_filtrado_columnas = pd.DataFrame(columnas_a_copy)
                df_filtrado_columnas['PLAZA_HOJA'] = plaza
                listado.append(df_filtrado_columnas.dropna(subset=['ORIGEN', 'DESTINO']))
                
        df_master = pd.concat(listado, ignore_index=True)
        df_master['ORIGEN'] = df_master['ORIGEN'].astype(str).str.strip().str.upper()
        df_master['DESTINO'] = df_master['DESTINO'].astype(str).str.strip().str.upper()
        df_horarios['ORIGEN'] = df_horarios['ORIGEN'].astype(str).str.strip().str.upper()
        df_horarios['DESTINO'] = df_horarios['DESTINO'].astype(str).str.strip().str.upper()
        
        # Homologación de Nombres de Plaza
        for df_tmp in [df_master, df_horarios]:
            df_tmp['DESTINO'] = df_tmp['DESTINO'].str.replace('GUTIERREZ', '').str.strip()
            df_tmp['ORIGEN'] = df_tmp['ORIGEN'].str.replace('GUTIERREZ', '').str.strip()
            df_tmp['DESTINO'] = df_tmp['DESTINO'].str.replace('MERIDA ANDREA', 'MERIDA').str.replace('CDC-MERIDA', 'MERIDA')
            df_tmp['ORIGEN'] = df_tmp['ORIGEN'].str.replace('MERIDA ANDREA', 'MERIDA').str.replace('CDC-MERIDA', 'MERIDA')
        
        df_master['FECHA_DT'] = pd.to_datetime(df_master['FECHA_SISTEMA'], errors='coerce')
        df_master = df_master[df_master['FECHA_DT'].dt.year > 2020]
        
        # Días de la semana en español
        dias_espanol = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
        df_master['Dia_Semana_Num'] = df_master['FECHA_DT'].dt.dayofweek
        df_master['Día de la Semana'] = df_master['Dia_Semana_Num'].map(dias_espanol)
        
        meses_espanol = {
            'January': 'Enero', 'February': 'Febrero', 'March': 'Marzo', 'April': 'Abril',
            'May': 'Mayo', 'June': 'Junio', 'July': 'Julio', 'August': 'Agosto',
            'September': 'Septiembre', 'October': 'Octubre', 'November': 'Noviembre', 'December': 'Diciembre'
        }
        df_master['Mes_Num'] = df_master['FECHA_DT'].dt.month
        df_master['Mes'] = df_master['FECHA_DT'].dt.strftime('%B').map(meses_espanol)
        
        df_master['RUTA_KEY'] = df_master['ORIGEN'].str.replace(" ", "") + "_" + df_master['DESTINO'].str.replace(" ", "")
        df_horarios['RUTA_KEY'] = df_horarios['ORIGEN'].str.replace(" ", "") + "_" + df_horarios['DESTINO'].str.replace(" ", "")
        
        df_horarios_clean = df_horarios.drop_duplicates(subset=['RUTA_KEY'])[['RUTA_KEY', 'HORA SALIDA', 'HORA LLEGADA DESTINO FINAL']].copy()
        df_horarios_clean.columns = ['RUTA_KEY', 'TEORICA_SALIDA', 'TEORICA_LLEGADA']
        
        df_unificado = pd.merge(df_master, df_horarios_clean, on='RUTA_KEY', how='left')
        
        def parse_horario_flexible(h_val):
            if pd.isna(h_val) or str(h_val).strip() == "" or str(h_val).lower() in ["nan", "none", "pendiente", "variable"]:
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
            
            if dif > 15: return dif, "Demorado"
            elif dif < -15: return dif, "Antes de Tiempo"
            else: return dif, "On Time"

        res_salida = df_unificado.apply(lambda r: evaluar_tiempo_absoluto(r['HORA SALIDA REAL'], r['TEORICA_SALIDA']), axis=1)
        df_unificado['MINUTOS_DIF_SALIDA'] = [x[0] for x in res_salida]
        df_unificado['ESTATUS_SALIDA'] = [x[1] for x in res_salida]

        res_llegada = df_unificado.apply(lambda r: evaluar_tiempo_absoluto(r['HORA LLEGADA REAL'], r['TEORICA_LLEGADA']), axis=1)
        df_unificado['MINUTOS_DIF_LLEGADA'] = [x[0] for x in res_llegada]
        df_unificado['ESTATUS_LLEGADA'] = [x[1] for x in res_llegada]

        # --- FILTROS SIDEBAR ---
        st.sidebar.header("🕹️ Filtros de Control")
        meses_disp = list(df_unificado.sort_values('Mes_Num')['Mes'].unique())
        mes_sel = st.sidebar.multiselect("Periodo Mensual", meses_disp, default=meses_disp)
        df_f1 = df_unificado[df_unificado['Mes'].isin(mes_sel)]
        
        origen_disp = sorted(df_f1['ORIGEN'].unique().tolist())
        origen_sel = st.sidebar.multiselect("Plaza Origen", origen_disp, default=origen_disp)
        df_f2 = df_f1[df_f1['ORIGEN'].isin(origen_sel)]
        
        # Filtro de destino dinámico inteligente (en cascada)
        destino_disp = sorted(df_f2['DESTINO'].unique().tolist())
        destino_sel = st.sidebar.multiselect("Plaza Destino", destino_disp, default=destino_disp)
        
        df_filtrado = df_f2[df_f2['DESTINO'].isin(destino_sel)]

        df_sal_v = df_filtrado[df_filtrado['ESTATUS_SALIDA'].isin(['On Time', 'Demorado', 'Antes de Tiempo'])]
        df_lleg_v = df_filtrado[df_filtrado['ESTATUS_LLEGADA'].isin(['On Time', 'Demorado', 'Antes de Tiempo'])]
        
        # --- RESUMEN KPIs DIRECTIVOS ---
        st.markdown("#### 📊 Resumen Ejecutivo de Desempeño")
        k1, k2, k3, k4 = st.columns(4)
        
        pct_sal = (df_sal_v['ESTATUS_SALIDA'] == 'On Time').sum() / len(df_sal_v) * 100 if len(df_sal_v)>0 else 0
        k1.metric("On-Time Despacho (Salidas)", f"{pct_sal:.1f}%", f"{len(df_sal_v)} viajes con horario")
        
        pct_lleg = (df_lleg_v['ESTATUS_LLEGADA'] == 'On Time').sum() / len(df_lleg_v) * 100 if len(df_lleg_v)>0 else 0
        k2.metric("On-Time Cumplimiento (Llegadas)", f"{pct_lleg:.1f}%", f"{len(df_lleg_v)} viajes con arribo")
        
        avg_sal_min = df_sal_v[df_sal_v['MINUTOS_DIF_SALIDA'] > 0]['MINUTOS_DIF_SALIDA'].mean()
        txt_avg_sal = formatear_minutos_a_string(avg_sal_min) if pd.notna(avg_sal_min) else "0 min"
        k3.metric("Retraso Promedio en Salida", txt_avg_sal, "Desviación promedio por circuito")
        
        pendientes = (df_filtrado['ESTATUS_LLEGADA'] == "Pendiente / Sin Captura").sum()
        k4.metric("Viajes con Llegada Pendiente", f"{pendientes} Viajes", "Falta reporte en destino")
        
        st.markdown("---")
        
        # --- PESTAÑAS ---
        tab_volumen, tab_rutas, tab_operadores, tab_incidencias = st.tabs([
            "🌐 Análisis por Mes y Día", 
            "🚨 Análisis de Rutas Críticas", 
            "👤 Confiabilidad de Operadores",
            "💬 Bitácora de Incidencias"
        ])
        
        with tab_volumen:
            st.subheader("Evaluación Temporal de Controles")
            
            c_g1, c_g2 = st.columns(2)
            with c_g1:
                st.markdown("**Volumen de Circuitos por Estatus Mensual**")
                if len(df_sal_v) > 0:
                    fig_m_sal = px.histogram(df_sal_v, x='Mes', color='ESTATUS_SALIDA', barmode='group',
                                             labels={'count': 'Viajes', 'Mes': 'Mes'},
                                             color_discrete_map={'On Time':'#2ca02c', 'Demorado':'#d62728', 'Antes de Tiempo':'#1f77b4'})
                    fig_m_sal.update_layout(yaxis_title="Cantidad de Viajes")
                    st.plotly_chart(fig_m_sal, use_container_width=True)
            
            with c_g2:
                st.markdown("**Análisis Crítico por Día de la Semana (Identificación de Días de Atraso)**")
                if len(df_sal_v) > 0:
                    df_dias = df_sal_v.sort_values('Dia_Semana_Num')
                    fig_d_sal = px.histogram(df_dias, x='Día de la Semana', color='ESTATUS_SALIDA', barmode='group',
                                             color_discrete_map={'On Time':'#2ca02c', 'Demorado':'#d62728', 'Antes de Tiempo':'#1f77b4'})
                    fig_d_sal.update_layout(yaxis_title="Cantidad de Viajes")
                    st.plotly_chart(fig_d_sal, use_container_width=True)
            
            st.markdown("---")
            st.markdown("### Apertura de Eficiencia y Destinos por CEDIS Origen")
            
            col_pl1, col_pl2 = st.columns([1, 1])
            with col_pl1:
                st.markdown("**% On-Time de Salida por CEDIS**")
                if len(df_sal_v) > 0:
                    plaza_perf = df_sal_v.groupby('ORIGEN').apply(lambda x: (x['ESTATUS_SALIDA']=='On Time').sum()/len(x)*100).reset_index(name='% On-Time Salida').sort_values('% On-Time Salida', ascending=False)
                    fig_bar_p = px.bar(plaza_perf, x='ORIGEN', y='% On-Time Salida', color='% On-Time Salida', color_continuous_scale='RdYlGn', text='% On-Time Salida')
                    fig_bar_p.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                    st.plotly_chart(fig_bar_p, use_container_width=True)
            with col_pl2:
                st.markdown("**Detalle de Cumplimiento por Destinos del Origen**")
                df_destinos_perf = df_sal_v.groupby(['ORIGEN', 'DESTINO']).agg(
                    Total_Viajes=('FOLIO', 'count'),
                    Salidas_A_Tiempo=('ESTATUS_SALIDA', lambda x: (x == 'On Time').sum())
                ).reset_index()
                df_destinos_perf['% Eficiencia'] = (df_destinos_perf['Salidas_A_Tiempo'] / df_destinos_perf['Total_Viajes'] * 100).round(1)
                st.dataframe(df_destinos_perf[['ORIGEN', 'DESTINO', 'Total_Viajes', '% Eficiencia']].sort_values(by='% Eficiencia', ascending=False), use_container_width=True, hide_index=True)

        with tab_rutas:
            st.subheader("Tramos con Mayor Desviación en Horas y Minutos")
            col_r1, col_r2 = st.columns(2)
            
            with col_r1:
                st.markdown("📋 **Desviaciones en Despacho (SALIDAS)**")
                df_dem_sal = df_sal_v[df_sal_v['MINUTOS_DIF_SALIDA'] > 15]
                if len(df_dem_sal) > 0:
                    rutas_sal = df_dem_sal.groupby(['ORIGEN', 'DESTINO']).agg(
                        Viajes_Demorados=('FOLIO', 'count'),
                        Promedio_Minutos=('MINUTOS_DIF_SALIDA', 'mean'),
                        Maximo_Minutos=('MINUTOS_DIF_SALIDA', 'max')
                    ).reset_index().sort_values(by='Viajes_Demorados', ascending=False)
                    
                    rutas_sal['Retraso Prom'] = rutas_sal['Promedio_Minutos'].apply(formatear_minutos_a_string)
                    rutas_sal['Retraso Max'] = rutas_sal['Maximo_Minutos'].apply(formatear_minutos_a_string)
                    
                    st.dataframe(rutas_sal[['ORIGEN', 'DESTINO', 'Viajes_Demorados', 'Retraso Prom', 'Retraso Max']], use_container_width=True, hide_index=True)
                else:
                    st.success("Sin demoras registradas en salidas.")
                    
            with col_r2:
                st.markdown("📋 **Desviaciones en Destino Final (LLEGADAS)**")
                df_dem_lleg = df_lleg_v[df_lleg_v['MINUTOS_DIF_LLEGADA'] > 15]
                if len(df_dem_lleg) > 0:
                    rutas_lleg = df_dem_lleg.groupby(['ORIGEN', 'DESTINO']).agg(
                        Viajes_Demorados=('FOLIO', 'count'),
                        Promedio_Minutos=('MINUTOS_DIF_LLEGADA', 'mean'),
                        Maximo_Minutos=('MINUTOS_DIF_LLEGADA', 'max')
                    ).reset_index().sort_values(by='Viajes_Demorados', ascending=False)
                    
                    r_lleg_df = rutas_lleg.copy()
                    r_lleg_df['Retraso Prom'] = r_lleg_df['Promedio_Minutos'].apply(formatear_minutos_a_string)
                    r_lleg_df['Retraso Max'] = r_lleg_df['Maximo_Minutos'].apply(formatear_minutos_a_string)
                    
                    st.dataframe(r_lleg_df[['ORIGEN', 'DESTINO', 'Viajes_Demorados', 'Retraso Prom', 'Retraso Max']], use_container_width=True, hide_index=True)
                else:
                    st.success("Sin demoras registradas en arribos.")

        with tab_operadores:
            st.subheader("Matriz de Confiabilidad Unificada por Operador")
            st.markdown("*Nombres agrupados y consolidados sin duplicaciones. Ordenado de Mayor a Menor Eficiencia General.*")
            
            if len(df_filtrado) > 0:
                op_stats = df_filtrado.groupby(['OPERADOR']).agg(
                    Total_Viajes=('FOLIO', 'count'),
                    Salidas_Evaluadas=('ESTATUS_SALIDA', lambda x: x.isin(['On Time', 'Demorado', 'Antes de Tiempo']).sum()),
                    Salidas_On_Time=('ESTATUS_SALIDA', lambda x: (x == 'On Time').sum()),
                    Llegadas_Evaluadas=('ESTATUS_LLEGADA', lambda x: x.isin(['On Time', 'Demorado', 'Antes de Tiempo']).sum()),
                    Llegadas_On_Time=('ESTATUS_LLEGADA', lambda x: (x == 'On Time').sum())
                ).reset_index()
                
                op_stats['% On-Time Salida'] = (op_stats['Salidas_On_Time'] / op_stats['Salidas_Evaluadas'] * 100).fillna(0)
                op_stats['% On-Time Llegada'] = (op_stats['Llegadas_On_Time'] / op_stats['Llegadas_Evaluadas'] * 100).fillna(0)
                
                op_stats['% On-Time General'] = (op_stats['% On-Time Salida'] + op_stats['% On-Time Llegada']) / 2
                
                op_reporte = op_stats[['OPERADOR', 'Total_Viajes', '% On-Time Salida', '% On-Time Llegada', '% On-Time General']].copy()
                op_reporte = op_reporte.sort_values(by='% On-Time General', ascending=False)
                
                st.dataframe(op_reporte.style.format({
                    '% On-Time Salida': '{:.1f}%',
                    '% On-Time Llegada': '{:.1f}%',
                    '% On-Time General': '{:.1f}%',
                    'Total_Viajes': '{:.0f}'
                }), use_container_width=True, hide_index=True)

        with tab_incidencias:
            st.subheader("Bitácora General de Incidencias Operativas")
            
            df_comentarios = df_filtrado[df_filtrado['COMENTARIOS_SISTEMA'].notna() & (df_filtrado['COMENTARIOS_SISTEMA'] != "") & (df_filtrado['COMENTARIOS_SISTEMA'] != "0") & (df_filtrado['COMENTARIOS_SISTEMA'] != 0)]
            
            df_inc_tabla = pd.DataFrame()
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
