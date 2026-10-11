import pandas as pd
import numpy as np

from construir_referencia import clave_sujeto, sienax_fiable, corregir_sienax

UMBRAL_Z = 2.0
MIN_SUJETOS_SUBGRUPO = 30
VENTANA_EDAD = 5  # años

# Métricas que se evalúan. Los nombres coinciden con las claves del resultado de core_neuro.py
# y con las columnas del CSV de referencia (que genera construir_referencia.py).
METRICAS_ABSOLUTAS = [
    "materia_gris", "materia_blanca", "liquido_cefalorraquideo", "volumen_intracraneal_total",
]
# Normalizadas por SIENAX (ya corregidas por tamaño de cabeza)
METRICAS_NORMALIZADAS = [
    "materia_gris_normalizada", "materia_blanca_normalizada", "volumen_cerebral_total_normalizado",
]


def cargar_demografia_pacientes(ruta_csv: str) -> dict:
    """
    CSV opcional con columnas: paciente, edad, sexo (M/F).
    'paciente' debe coincidir con el sujeto BIDS (p. ej. sub-0050).
    Devuelve {paciente: {"edad": float, "sexo": "M"|"F"|None}}.
    """
    df = pd.read_csv(ruta_csv)
    datos = {}
    for _, fila in df.iterrows():
        sexo = str(fila.get("sexo", "")).strip().upper()
        datos[str(fila["paciente"])] = {
            "edad": float(fila["edad"]) if pd.notna(fila.get("edad")) else None,
            "sexo": "M" if sexo in ("M", "H", "1", "HOMBRE") else "F" if sexo in ("F", "MUJER", "2") else None,
        }
    return datos


class StatsEngine:
    """
    Z-scores frente a una referencia sana procesada con el MISMO pipeline
    (HD-BET + FAST + SIENAX), así que las medidas son directamente comparables.
    """

    def __init__(self, ruta_referencia, datos_pacientes=None):
        print("==================================================")
        print("   MedVision - Motor Estadístico Headless (Z-Scores)")
        print("==================================================\n")
        self.ruta_referencia = ruta_referencia
        self.datos_pacientes = datos_pacientes or {}
        self.df_referencia = None

    def preparar_motor(self):
        df = pd.read_csv(self.ruta_referencia, low_memory=False)
        n_sesiones = len(df)
        # Acepta M/F y también CSV antiguos con 1/2
        df["sexo"] = df["sexo"].map({"M": "M", "F": "F", 1: "M", 2: "F", "1": "M", "2": "F"})

        # Un solo escaneo por sujeto (la primera sesión), para que nadie pese más que otro
        df = df.dropna(subset=["materia_gris"])
        df = df.sort_values(["clave", "sesion"]).drop_duplicates("clave", keep="first").copy()

        self.df_referencia = df
        print(f"-> Referencia propia cargada: {len(df)} sujetos únicos ({n_sesiones} sesiones en el CSV).")
        if len(df) < MIN_SUJETOS_SUBGRUPO:
            print(f"   [AVISO] Con menos de {MIN_SUJETOS_SUBGRUPO} sujetos los Z-Scores son poco fiables.")
        print()
        return self.df_referencia

    def _subgrupo(self, referencia, edad, sexo):
        """Mismo sexo y edad ±VENTANA_EDAD. Si queda muy pequeño, se usa la referencia entera."""
        if sexo in ("M", "F") and edad is not None:
            sub = referencia[(referencia["sexo"] == sexo) & ((referencia["edad"] - edad).abs() <= VENTANA_EDAD)]
            if len(sub) >= MIN_SUJETOS_SUBGRUPO:
                return sub, f"mismo sexo y edad {edad:.0f}±{VENTANA_EDAD} años"
            print(f"   [AVISO] Solo {len(sub)} sanos comparables (sexo/edad); se usa la referencia completa.")
        else:
            print("   [AVISO] Sin edad/sexo del paciente: se compara con la referencia completa.")
        return referencia, "referencia completa"

    def evaluar_diccionarios_paciente(self, lista_resultados_fsl):
        """
        Recibe la lista de diccionarios de core_neuro.py y añade:
          - z_scores: un Z por métrica (absolutas y, si hay SIENAX, normalizadas)
          - anomalias_zscore_detectadas: cuántas superan |Z| > UMBRAL_Z
          - referencia_zscore: con cuántos sanos y con qué criterio se comparó
        """
        if self.df_referencia is None:
            self.preparar_motor()

        for resultado in lista_resultados_fsl:
            if resultado.get("tipo") != "transversal":
                continue

            sujeto = resultado.get("paciente", "Desconocido")
            print(f" -> Evaluando estadísticamente el sujeto: {sujeto}")

            # Si este mismo sujeto está en la referencia, se excluye para no compararlo consigo mismo
            referencia = self.df_referencia[self.df_referencia["clave"] != clave_sujeto(sujeto)]
            demo = self.datos_pacientes.get(sujeto, {})
            referencia, criterio = self._subgrupo(referencia, demo.get("edad"), demo.get("sexo"))

            valores = {}
            vol_fast = resultado.get("volumenes_absolutos_mm3") or {}
            valores.update(vol_fast)
            sienax = corregir_sienax(resultado.get("volumenes_sienax_normalizados") or {})
            fast_total = (vol_fast.get("materia_gris") or 0) + (vol_fast.get("materia_blanca") or 0)
            if sienax_fiable(sienax, fast_total):
                valores.update(sienax)
            elif sienax:
                print(f"   [AVISO] SIENAX no es fiable para este cerebro (v_scale={sienax.get('v_scale')}, "
                      f"opciones_bet={sienax.get('opciones_bet')}): se omiten los Z-Scores normalizados "
                      f"y se usan solo los de FAST.")

            z_scores = {}
            anomalias = 0
            for metrica in METRICAS_ABSOLUTAS + METRICAS_NORMALIZADAS:
                val = valores.get(metrica)
                if val is None or metrica not in referencia.columns:
                    continue
                sanos = referencia[metrica].dropna()
                if len(sanos) < 2:
                    continue
                media = np.mean(sanos)
                sigma = np.std(sanos, ddof=1)
                if sigma <= 0:
                    continue

                z = (val - media) / sigma
                z_scores[f"z_score_{metrica}"] = round(float(z), 2)
                if abs(z) > UMBRAL_Z:
                    anomalias += 1
                    print(f"   [!] ANOMALÍA en [{metrica}] -> Paciente: {val:.1f} | Media: {media:.1f} | Z-Score: {z:.2f}")

            print(f"   Referencia usada: {len(referencia)} sanos ({criterio}).")
            resultado["z_scores"] = z_scores
            resultado["anomalias_zscore_detectadas"] = anomalias
            resultado["referencia_zscore"] = {"n_sanos": int(len(referencia)), "criterio": criterio}

        return lista_resultados_fsl