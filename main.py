import os
import json
import argparse
from datetime import datetime

# Importaciones de los submódulos de MedVision
from config_manager import cargar_configuracion
from core_neuro import procesar_transversal, procesar_longitudinal
from data_reports import cargar_o_crear_informe, fusionar_resultado, guardar_json, generar_html

# Importación del Motor Estadístico (Z-Scores)
from stats_engine import StatsEngine, cargar_demografia_pacientes
from construir_referencia import OPCIONES_BET_SIENAX

RUTA_REFERENCIA = "data/referencia_medvision.csv"

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline Headless MedVision")
    parser.add_argument("-o", "--output", required=True, help="Carpeta de salida")
    parser.add_argument("-c", "--config", required=True, help="Archivo config.ini")

    subparsers = parser.add_subparsers(dest="modo", required=True)

    # Modo Transversal
    p_transversal = subparsers.add_parser("t", help="Analiza una resonancia en un solo momento")
    p_transversal.add_argument("-i", "--input", required=True, help="Archivo .nii.gz o carpeta con varios")
    p_transversal.add_argument("--sienax", action="store_true", help="Además de FAST, ejecuta SIENAX")
    p_transversal.add_argument("--zscores", action="store_true", help="Calcula Z-Scores comparando con la referencia sana")
    p_transversal.add_argument("--demografia", required=False, help="CSV con paciente, edad y sexo para afinar el Z-Score")

    # Modo Longitudinal
    p_longitudinal = subparsers.add_parser("l", help="Compara dos sesiones del mismo paciente con SIENA")
    p_longitudinal.add_argument("--a", dest="basal", required=True, help="Resonancia de la sesión más Antigua")
    p_longitudinal.add_argument("--r", dest="seguimiento", required=True, help="Resonancia de la sesión más Reciente")

    return parser

def guardar_json_atomico(informe: dict, ruta: str):
    """Escribe a un temporal y lo renombra: si se corta la luz a mitad, el JSON anterior sigue intacto."""
    temporal = ruta + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=4, ensure_ascii=False)
    os.replace(temporal, ruta)

def sesiones_ya_procesadas(informe: dict, exigir_sienax: bool) -> set:
    """
    (sujeto, sesion) que ya tienen volúmenes en el JSON. Con --sienax, solo cuentan si SIENAX se calculó
    con las opciones de BET actuales: los cerebros calculados antes (sin ellas) se reprocesan solos.
    """
    hechas = set()
    for sujeto, datos in informe.get("pacientes", {}).items():
        for sesion, s in datos.get("sesiones", {}).items():
            if not s.get("volumenes_absolutos_mm3"):
                continue
            if exigir_sienax:
                sienax = s.get("volumenes_sienax_normalizados") or {}
                if sienax.get("opciones_bet") != OPCIONES_BET_SIENAX:
                    continue
            hechas.add((sujeto, sesion))
    return hechas

def main():
    parser = construir_parser()
    args = parser.parse_args()

    print("==================================================")
    print("      MedVision - Análisis Volumétrico CLI        ")
    print("==================================================\n")

    try:
        config = cargar_configuracion(args.config)
    except (FileNotFoundError, KeyError) as e:
        print(f"[ERROR CRÍTICO] {e}")
        return

    ruta_hdbet = config['Rutas'].get('hdbet', 'hd-bet')
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    ruta_informe_json = os.path.join(output_dir, "informe_volumetrico_medvision.json")

    if args.modo == "t":
        informe = cargar_o_crear_informe(ruta_informe_json)

        # Preparar los Z-Scores ANTES de empezar: si falta la referencia, se sabe en el segundo 0
        # y no tras horas de procesamiento.
        motor = None
        if args.zscores:
            if os.path.exists(RUTA_REFERENCIA):
                datos_pacientes = cargar_demografia_pacientes(args.demografia) if args.demografia else {}
                motor = StatsEngine(RUTA_REFERENCIA, datos_pacientes=datos_pacientes)
                motor.preparar_motor()
            else:
                print(f"[AVISO] No existe {RUTA_REFERENCIA}. Se procesa sin Z-Scores "
                      f"(créala con construir_referencia.py).\n")

        def guardar_progreso(resultado: dict):
            """Se ejecuta tras CADA cerebro: Z-Scores (si toca) y JSON actualizado al momento."""
            if motor is not None:
                motor.evaluar_diccionarios_paciente([resultado])
            fusionar_resultado(informe, resultado)
            guardar_json_atomico(informe, ruta_informe_json)

        ya = sesiones_ya_procesadas(informe, exigir_sienax=args.sienax)
        resultados = procesar_transversal(args, ruta_hdbet, output_dir,
                                          ya_procesados=ya, al_terminar=guardar_progreso)
    else:
        resultados = procesar_longitudinal(args, output_dir)
        if resultados:
            informe = cargar_o_crear_informe(ruta_informe_json)
            for resultado in resultados:
                fusionar_resultado(informe, resultado)
            guardar_json_atomico(informe, ruta_informe_json)

    if not resultados:
        print("No se generaron resultados nuevos en esta ejecución.")
        return

    ruta_informe_html = os.path.join(
        output_dir, f"informe_{args.modo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    )
    generar_html(resultados, ruta_informe_html)

    print("\n=== PROCESO FINALIZADO ===")
    print(f"JSON actualizado: {ruta_informe_json}")
    print(f"HTML generado:    {ruta_informe_html}")

if __name__ == "__main__":
    main()