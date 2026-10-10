import pandas as pd
import numpy as np

class StatsEngine:
    def __init__(self, ruta_sanos, ruta_volumenes_freesurfer):
        print("==================================================")
        print("   MedVision - Motor Estadístico Headless (Z-Scores)")
        print("==================================================\n")
        
        self.ruta_sanos = ruta_sanos
        self.ruta_volumenes = ruta_volumenes_freesurfer
        self.df_referencia = None
        
    def preparar_motor(self):
        df_sanos = pd.read_csv(self.ruta_sanos, low_memory=False)
        df_vol = pd.read_csv(self.ruta_volumenes, low_memory=False)
        
        col_sanos = 'PTID' if 'PTID' in df_sanos.columns else 'Subject ID'
        col_vol = 'PTID' if 'PTID' in df_vol.columns else ('Subject ID' if 'Subject ID' in df_vol.columns else 'RID')
        
        self.df_referencia = pd.merge(df_sanos, df_vol, left_on=col_sanos, right_on=col_vol, how='inner')
        print(f"-> Cohorte de referencia sana cargada: {len(self.df_referencia)} sujetos.\n")
        return self.df_referencia

    def evaluar_cerebros(self, df_pacientes):
        """
        Recibe uno o varios cerebros procesados, calcula los Z-Scores para todas
        las regiones anatómicas (ST...SV) frente a la cohorte sana y detecta anomalías.
        """
        if self.df_referencia is None:
            self.preparar_motor()
            
        # Identificar todas las columnas de volumen subcortical/cortical disponibles ('ST...')
        columnas_regiones = [c for c in self.df_referencia.columns if c.startswith('ST') and c.endswith('SV')]
        
        informes_globales = []
        
        for idx, paciente in df_pacientes.iterrows():
            id_paciente = paciente.get('PTID', paciente.get('Subject ID', f'Paciente_{idx}'))
            print(f"==================================================")
            print(f" Evaluando cerebro / paciente: {id_paciente}")
            print(f"==================================================")
            
            anomalias_detectadas = 0
            
            for reg in columnas_regiones:
                # Datos de la cohorte sana para esta región específica
                sanos_reg = self.df_referencia[reg].dropna()
                if len(sanos_reg) == 0:
                    continue
                
                media = np.mean(sanos_reg)
                sigma = np.std(sanos_reg, ddof=1)
                
                # Valor del cerebro a evaluar
                val_paciente = paciente.get(reg, np.nan)
                if pd.isna(val_paciente) or sigma == 0:
                    continue
                
                # Cálculo del Z-Score
                z = (val_paciente - media) / sigma
                
                # Criterio de anomalía estadística (ej: Z < -2.0 atrofia o Z > 2.0 inflamación/agrandamiento)
                es_anomalo = abs(z) > 2.0
                if es_anomalo:
                    anomalias_detectadas += 1
                    print(f"   [!] ANOMALÍA en [{reg}] -> Volumen: {val_paciente:.1f} | Media Sana: {media:.1f} | Z-Score: {z:.2f}")
            
            print(f"-> Evaluación final para {id_paciente}: {anomalias_detectadas} regiones con desviación significativa (|Z| > 2.0).\n")

    def evaluar_diccionarios_paciente(self, lista_resultados_fsl):
        """
        Recibe la lista de diccionarios generada por core_neuro.py,
        calcula los Z-Scores basándose en la cohorte sana y los añade al diccionario.
        """
        if self.df_referencia is None:
            self.preparar_motor()
            
        # Mapeo de métricas obtenidas por FSL FAST a las columnas FreeSurfer de ADNI
        mapeo_columnas = {
            "materia_gris": "ST154SV",
            "materia_blanca": "ST152SV",
            "liquido_cefalorraquideo": "ST7SV",
            "volumen_intracraneal_total": "ST10CV"
        }

        for resultado in lista_resultados_fsl:
            # Los z-scores volumétricos solo aplican a los análisis transversales
            if resultado.get("tipo") != "transversal":
                continue
                
            print(f" -> Evaluando estadísticamente el sujeto: {resultado.get('paciente', 'Desconocido')}")
            
            volumenes_paciente = resultado.get("volumenes_absolutos_mm3", {})
            z_scores_calculados = {}
            anomalias_detectadas = 0
            
            for clave_fast, columna_adni in mapeo_columnas.items():
                val_paciente = volumenes_paciente.get(clave_fast)
                
                if val_paciente is not None:
                    # Extraer la distribución normal de la cohorte sana para este tejido
                    sanos_reg = self.df_referencia[columna_adni].dropna()
                    
                    if not sanos_reg.empty:
                        media = np.mean(sanos_reg)
                        sigma = np.std(sanos_reg, ddof=1)
                        
                        if sigma > 0:
                            z = (val_paciente - media) / sigma
                            z_scores_calculados[f"z_score_{clave_fast}"] = round(z, 2)
                            
                            # Notificar si sobrepasa tu umbral estadístico (|Z| > 2.0)
                            if abs(z) > 2.0:
                                anomalias_detectadas += 1
                                print(f"   [!] ANOMALÍA en [{clave_fast}] -> Paciente: {val_paciente:.1f} | Media: {media:.1f} | Z-Score: {z:.2f}")

            # Guardamos los cálculos en el diccionario que irá al JSON y al HTML
            resultado["z_scores"] = z_scores_calculados
            resultado["anomalias_zscore_detectadas"] = anomalias_detectadas
            
        return lista_resultados_fsl

if __name__ == "__main__":
    CSV_SANOS = "data/cohorte_sanos_referencia.csv"
    CSV_FREESURFER = "data/UCSFFSX7_06Oct2026.csv" 
    
    motor = StatsEngine(CSV_SANOS, CSV_FREESURFER)
    motor.preparar_motor()
    
    # SIMULACIÓN HEADLESS: Cogemos por ejemplo los primeros 3 cerebros de la propia tabla
    # (puedes pasarle cualquier otro DataFrame con la misma estructura de columnas de pacientes a evaluar)
    df_prueba_pacientes = pd.read_csv(CSV_FREESURFER, low_memory=False).head(3)
    
    motor.evaluar_cerebros(df_prueba_pacientes)