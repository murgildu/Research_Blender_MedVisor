"""
Construye la base de datos de referencia (CSV) a partir del JSON acumulativo que genera MedVision.

Uso:
    python construir_referencia.py -j salida/informe_volumetrico_medvision.json -o data/referencia_medvision.csv

Se puede ejecutar tantas veces como quieras: lee SIEMPRE el JSON completo y regenera el CSV,
así que a medida que procesas más lotes la referencia crece sola.

Edad y sexo se sacan de idaSearch (columnas Subject ID, Sex, Age) emparejando el ID de ADNI
con el sujeto del JSON (sub-002S0413 y 002_S_0413 se consideran el mismo sujeto).
"""
import argparse
import json
import os
import re

import pandas as pd

# --- Control de calidad de SIENAX --------------------------------------------------
# Criterio principal: el volumen cerebral de SIENAX (sin normalizar) debe coincidir con el que
# mide FAST sobre la máscara de HD-BET (materia gris + blanca). Con las opciones actuales,
# en 51 cerebros la proporción SIENAX/FAST es 0.97 +- 0.03; los registros fallidos daban 1.4-9.5.
# Si SIENAX falla, sus valores normalizados no sirven; los de FAST (absolutos) sí.
VSCALE_MIN, VSCALE_MAX = 0.7, 2.2           # solo una cota de cordura
RATIO_MIN, RATIO_MAX = 0.8, 1.2             # SIENAX sin normalizar / FAST (GM+WM)

# Opciones de BET con las que se ejecuta SIENAX (-B = limpieza de cuello). Sin ellas, el BET
# interno de SIENAX incluía cuello/cara en muchos escáneres. Cada cerebro guarda con qué opciones
# se calculó, y los calculados sin ellas no entran en la referencia.
OPCIONES_BET_SIENAX = "-B"

_PARES_NORMALIZADO = [
    ("materia_gris_normalizada", "materia_gris_sin_normalizar"),
    ("materia_blanca_normalizada", "materia_blanca_sin_normalizar"),
    ("volumen_cerebral_total_normalizado", "volumen_cerebral_total_sin_normalizar"),
]


def corregir_sienax(sienax: dict) -> dict:
    """
    Los JSON anteriores guardaban en *_normalizada/o la columna SIN normalizar de report.sienax
    (la segunda, por un error de lectura). El valor normalizado real es ese valor x v_scale.
    Devuelve una copia corregida (o el mismo dict si ya lo estaba). Es idempotente.
    """
    if not sienax or sienax.get("columnas_corregidas"):
        return sienax
    v = sienax.get("v_scale")
    if v is None:
        return sienax
    nuevo = dict(sienax)
    for col_norm, col_sin in _PARES_NORMALIZADO:
        if col_norm in sienax:
            nuevo[col_sin] = sienax[col_norm]
            nuevo[col_norm] = round(sienax[col_norm] * v, 2)
    nuevo["columnas_corregidas"] = True
    return nuevo


def sienax_fiable(sienax: dict, fast_total) -> bool:
    """
    Calculado con las opciones de BET actuales Y coherente con FAST.
    fast_total = materia gris + materia blanca de FAST (mm3).
    """
    sienax = corregir_sienax(sienax or {})
    if sienax.get("opciones_bet") != OPCIONES_BET_SIENAX:
        return False
    v = sienax.get("v_scale")
    nativo = sienax.get("volumen_cerebral_total_sin_normalizar")
    if v is None or nativo is None or not fast_total or pd.isna(v) or pd.isna(nativo):
        return False
    return VSCALE_MIN <= v <= VSCALE_MAX and RATIO_MIN <= nativo / fast_total <= RATIO_MAX


COLUMNAS_ABSOLUTAS = [
    "materia_gris", "materia_blanca", "liquido_cefalorraquideo", "volumen_intracraneal_total",
]
COLUMNAS_SIENAX = [
    "v_scale", "materia_gris_normalizada", "materia_blanca_normalizada",
    "volumen_cerebral_total_normalizado", "volumen_cerebral_total_sin_normalizar",
]


def clave_sujeto(identificador) -> str:
    """'sub-002S0413', 'sub-002_S_0413' y '002_S_0413' -> '002S0413'."""
    texto = str(identificador)
    if texto.startswith("sub-"):
        texto = texto[4:]
    return re.sub(r"[^0-9A-Za-z]", "", texto).upper()


def cargar_demografia_ida(ruta_ida: str) -> dict:
    if not ruta_ida or not os.path.exists(ruta_ida):
        print("[AVISO] No se encontró idaSearch: la referencia no tendrá edad ni sexo.")
        return {}
    ida = pd.read_csv(ruta_ida, low_memory=False)
    ida = ida[ida["Sex"].isin(["M", "F"]) & ida["Age"].notna()].copy()
    ida["clave"] = ida["Subject ID"].map(clave_sujeto)
    ida = ida.drop_duplicates("clave")
    return {
        fila["clave"]: {"edad": float(fila["Age"]), "sexo": fila["Sex"]}  # "M" o "F"
        for _, fila in ida.iterrows()
    }


def cargar_sanos(ruta_sanos: str):
    """Conjunto de claves de los sujetos sanos permitidos en la referencia (o None = todos)."""
    if not ruta_sanos or not os.path.exists(ruta_sanos):
        print("[AVISO] No se encontró la lista de sanos: la referencia incluirá TODOS los sujetos del JSON.")
        return None
    df = pd.read_csv(ruta_sanos)
    col = "Subject ID" if "Subject ID" in df.columns else "PTID"
    return set(df[col].map(clave_sujeto))


def construir(ruta_json: str, ruta_salida: str, ruta_ida: str = None,
              ruta_sanos: str = None) -> pd.DataFrame:
    with open(ruta_json, "r", encoding="utf-8") as f:
        informe = json.load(f)

    demografia = cargar_demografia_ida(ruta_ida)
    sanos = cargar_sanos(ruta_sanos)
    excluidos = []
    filas = []

    for sujeto, datos in informe.get("pacientes", {}).items():
        for sesion, s in datos.get("sesiones", {}).items():
            vol = s.get("volumenes_absolutos_mm3") or {}
            if not vol:
                continue
            sienax = corregir_sienax(s.get("volumenes_sienax_normalizados") or {})
            clave = clave_sujeto(sujeto)
            if sanos is not None and clave not in sanos:
                excluidos.append(sujeto)
                continue
            demo = demografia.get(clave, {})

            fila = {"sujeto": sujeto, "clave": clave, "sesion": sesion,
                    "edad": demo.get("edad"), "sexo": demo.get("sexo")}
            for c in COLUMNAS_ABSOLUTAS:
                fila[c] = vol.get(c)
            for c in COLUMNAS_SIENAX:
                fila[c] = sienax.get(c)
            # Si SIENAX falló, sus valores normalizados se dejan vacíos (los absolutos de FAST se conservan)
            fast_total = (vol.get("materia_gris") or 0) + (vol.get("materia_blanca") or 0)
            fila["qc_sienax"] = sienax_fiable(sienax, fast_total)
            if not fila["qc_sienax"]:
                for c in COLUMNAS_SIENAX:
                    if c != "v_scale":
                        fila[c] = None
            filas.append(fila)

    df = pd.DataFrame(filas)
    if df.empty:
        print("[AVISO] El JSON no tiene ninguna sesión transversal con volúmenes. No se crea el CSV.")
        return df

    os.makedirs(os.path.dirname(os.path.abspath(ruta_salida)), exist_ok=True)
    df.to_csv(ruta_salida, index=False)

    print(f"-> Referencia guardada en {ruta_salida}")
    print(f"   {len(df)} sesiones | {df['clave'].nunique()} sujetos")
    print(f"   con edad y sexo: {df['edad'].notna().sum()} | con SIENAX válido: {int(df['qc_sienax'].sum())}"
          f" | SIENAX descartado por QC: {int((~df['qc_sienax']).sum())}")
    if excluidos:
        print(f"   excluidos por no estar en la lista de sanos: {', '.join(excluidos)}")
    return df


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Convierte el JSON de MedVision en CSV de referencia")
    p.add_argument("-j", "--json", required=True, help="informe_volumetrico_medvision.json")
    p.add_argument("-o", "--output", default="data/referencia_medvision.csv")
    p.add_argument("--ida", default="data/idaSearch_10_06_2026.csv", help="CSV con Subject ID, Sex, Age")
    p.add_argument("--sanos", default="data/lista_final_sanos_para_procesar.csv",
                   help="CSV con la lista de sanos permitidos (columna Subject ID); '' para no filtrar")
    args = p.parse_args()
    construir(args.json, args.output, args.ida, args.sanos)