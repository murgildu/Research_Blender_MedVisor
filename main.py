import os
import argparse
from datetime import datetime

# Importaciones de los submódulos de MedVision
from config_manager import cargar_configuracion
from core_neuro import procesar_transversal, procesar_longitudinal
from data_reports import cargar_o_crear_informe, fusionar_resultado, guardar_json, generar_html

# Importación del Motor Estadístico (Z-Scores)
from stats_engine import StatsEngine

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline Headless MedVision")
    parser.add_argument("-o", "--output", required=True, help="Carpeta de salida")
    parser.add_argument("-c", "--config", required=True, help="Archivo config.ini")

    subparsers = parser.add_subparsers(dest="modo", required=True)

    p_transversal = subparsers.add_parser(
        "t", help="Analiza una resonancia en un solo momento"
    )
    p_transversal.add_argument("-i", "--input", required=True,
                                help="Archivo .nii.gz o carpeta con varios")
    p_transversal.add_argument("--sienax", action="store_true",
                                help="Además de FAST, ejecuta SIENAX")

    p_longitudinal = subparsers.add_parser(
        "l", help="Compara dos sesiones del mismo paciente con SIENA"
    )
    p_longitudinal.add_argument("--a", dest="basal", required=True,
                                 help="Resonancia de la sesión más Antigua")
    p_longitudinal.add_argument("--r", dest="seguimiento", required=True,
                                 help="Resonancia de la sesión más Reciente")

    return parser

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

    # 1. FASE DE PROCESAMIENTO DE IMAGEN (HD-BET + FSL)
    if args.modo == "t":
        resultados = procesar_transversal(args, ruta_hdbet, output_dir)
    else:
        resultados = procesar_longitudinal(args, output_dir)

    if not resultados:
        print("No se generaron resultados en esta ejecución.")
        return

    # 2. FASE ESTADÍSTICA: Evaluación contra la cohorte de ADNI
    print("\n[Z-Scores] Comparando resultados del paciente con la base de datos ADNI...")
    ruta_sanos = "data/cohorte_sanos_referencia.csv"
    ruta_freesurfer = "data/UCSFFSX7_06Oct2026.csv"
    
    if os.path.exists(ruta_sanos) and os.path.exists(ruta_freesurfer):
        motor = StatsEngine(ruta_sanos, ruta_freesurfer)
        # Evaluamos y añadimos los cálculos estadísticos a la lista de resultados
        resultados = motor.evaluar_diccionarios_paciente(resultados)
    else:
        print("[AVISO] Faltan los CSV en 'data/'. Saltando el cálculo de Z-Scores.")

    # 3. FASE DE INFORMES
    ruta_informe_json = os.path.join(output_dir, "informe_volumetrico_medvision.json")
    informe = cargar_o_crear_informe(ruta_informe_json)
    
    for resultado in resultados:
        fusionar_resultado(informe, resultado)
    guardar_json(informe, ruta_informe_json)

    ruta_informe_html = os.path.join(
        output_dir, f"informe_{args.modo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    )
    generar_html(resultados, ruta_informe_html)

    print("\n=== PROCESO FINALIZADO ===")
    print(f"JSON actualizado: {ruta_informe_json}")
    print(f"HTML generado:    {ruta_informe_html}")

if __name__ == "__main__":
    main()