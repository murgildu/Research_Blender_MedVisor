"""
Corrige un informe_volumetrico_medvision.json generado antes del arreglo de lectura de SIENAX.

Problema: los campos materia_gris_normalizada, materia_blanca_normalizada y
volumen_cerebral_total_normalizado guardaban la columna SIN normalizar de report.sienax.
El valor normalizado real es ese valor x v_scale (SIENAX: normalizado = sin normalizar x VSCALING).

Esta corrección NO reprocesa nada: recalcula los campos a partir de los datos del propio JSON.
  - Guarda una copia de seguridad (<json>.bak_antes_correccion) la primera vez.
  - Es idempotente: las entradas ya corregidas no se tocan.

Uso:
    python corregir_json_sienax.py "salida_informe\\informe_volumetrico_medvision.json"
"""
import argparse
import json
import os
import shutil

from construir_referencia import corregir_sienax


def corregir_archivo(ruta_json: str) -> int:
    with open(ruta_json, "r", encoding="utf-8") as f:
        informe = json.load(f)

    corregidas = 0
    ya_estaban = 0
    for datos in informe.get("pacientes", {}).values():
        for s in datos.get("sesiones", {}).values():
            sienax = s.get("volumenes_sienax_normalizados")
            if not sienax:
                continue
            if sienax.get("columnas_corregidas"):
                ya_estaban += 1
                continue
            s["volumenes_sienax_normalizados"] = corregir_sienax(sienax)
            corregidas += 1

    if corregidas:
        copia = ruta_json + ".bak_antes_correccion"
        if not os.path.exists(copia):
            shutil.copy2(ruta_json, copia)
        temporal = ruta_json + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(informe, f, indent=4, ensure_ascii=False)
        os.replace(temporal, ruta_json)

    print(f"-> Sesiones corregidas: {corregidas} | ya estaban corregidas: {ya_estaban}")
    if corregidas:
        print(f"   Copia de seguridad: {ruta_json}.bak_antes_correccion")
    return corregidas


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Corrige los valores normalizados de SIENAX en el JSON")
    p.add_argument("json", help="informe_volumetrico_medvision.json")
    args = p.parse_args()
    corregir_archivo(args.json)