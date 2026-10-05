"""
headless.py — MedVision Pipeline Headless

Dos modos de uso (subcomandos), porque SIENAX y SIENA necesitan datos
de entrada distintos:

  Transversal (un paciente, un momento):
    python headless.py -o salida -c config.ini t -i carpeta_o_archivo [--sienax]

  Longitudinal (mismo paciente, dos fechas -> SIENA):
    python headless.py -o salida -c config.ini l --1 ses01.nii.gz --2 ses02.nii.gz

Arquitectura: cada modo CALCULA una lista de resultados (sin tocar
disco salvo los subprocess de FSL/HD-BET). Esos resultados se pasan,
SIN recalcular nada, a dos funciones de salida independientes:
guardar_json() y generar_html(). El JSON es la base de datos
acumulativa de todas las ejecuciones; el HTML es el informe de la
ejecucion actual, con las imagenes que SIENA/SIENAX ya generan
incrustadas en base64 (autocontenido).
"""
import os
import re
import json
import base64
import argparse
import subprocess
import configparser
from datetime import datetime

import nibabel as nib
import numpy as np


# ============================================================
# CONFIGURACION
# ============================================================

def cargar_configuracion(ruta_config: str) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    archivos_leidos = config.read(ruta_config, encoding='utf-8')
    if not archivos_leidos:
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {ruta_config}")
    if 'Rutas' not in config:
        raise KeyError(f"El archivo {ruta_config} no tiene la sección [Rutas].")
    return config


# ============================================================
# UTILIDADES DE RUTAS
# ============================================================

def a_wsl(ruta_win: str) -> str:
    """Convierte una ruta de Windows (D:\\...) a su equivalente en WSL (/mnt/d/...)."""
    ruta = ruta_win.replace('\\', '/')
    if ':' in ruta:
        letra, resto = ruta.split(':', 1)
        return f"/mnt/{letra.lower()}{resto}"
    return ruta


# ============================================================
# EJECUCION: HD-BET / FSL FAST
# ============================================================

def ejecutar_hdbet(ruta_hdbet: str, entrada: str, salida: str) -> bool:
    """Ejecuta HD-BET para la extracción del cráneo."""
    print("  -> Ejecutando HD-BET...")
    comando = [ruta_hdbet, "-i", entrada, "-o", salida]
    try:
        subprocess.run(comando, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError:
        print("  [ERROR] Falló la ejecución de HD-BET.")
        return False


def ejecutar_fsl_fast(ruta_entrada: str, directorio_salida: str, prefijo: str) -> bool:
    """Ejecuta FSL FAST a través de WSL forzando el PATH de Linux."""
    print("  -> Ejecutando FSL FAST (Segmentación PVE)...")

    ruta_entrada_wsl = a_wsl(ruta_entrada)
    ruta_base_salida_wsl = a_wsl(os.path.join(directorio_salida, prefijo))

    comando_linux = (
        f"source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; "
        f"fsl5.0-fast -t 1 -n 3 -p -o {ruta_base_salida_wsl} {ruta_entrada_wsl} "
        f"|| fast -t 1 -n 3 -p -o {ruta_base_salida_wsl} {ruta_entrada_wsl}"
    )
    comando = ["wsl", "bash", "-c", comando_linux]

    try:
        resultado = subprocess.run(comando, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"  [ERROR WSL] FAST falló.\n  STDERR: {resultado.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"  [FATAL] Error ejecutando comando WSL: {e}")
        return False


def calcular_volumen_tejido(ruta_imagen: str) -> float:
    """Calcula el volumen en mm3 a partir de un archivo NIfTI de probabilidad (PVE)."""
    if not os.path.exists(ruta_imagen):
        return 0.0
    try:
        img = nib.load(ruta_imagen)
        datos = img.get_fdata()
        voxel_dims = img.header.get_zooms()
        vol_voxel = voxel_dims[0] * voxel_dims[1] * voxel_dims[2]
        vol_total = np.sum(datos) * vol_voxel
        return round(vol_total, 2)
    except Exception as e:
        print(f"  [ERROR] Falló el cálculo de volumen: {e}")
        return 0.0


# ============================================================
# EJECUCION: SIENAX (transversal) / SIENA (longitudinal)
# ============================================================

def ejecutar_sienax(ruta_mri_original: str, dir_salida: str, prefijo: str) -> bool:
    """Ejecuta FSL SIENAX para el cálculo de volumen cerebral normalizado."""
    print(f"  -> Ejecutando SIENAX para {prefijo} (esto puede tardar unos minutos)...")

    dir_sienax = os.path.join(dir_salida, f"{prefijo}_sienax")
    ruta_mri_wsl = a_wsl(ruta_mri_original)
    dir_sienax_wsl = a_wsl(dir_sienax)

    comando_linux = (
        f"source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; "
        f"fsl5.0-sienax {ruta_mri_wsl} -o {dir_sienax_wsl} "
        f"|| sienax {ruta_mri_wsl} -o {dir_sienax_wsl}"
    )
    comando = ["wsl", "bash", "-c", comando_linux]

    try:
        resultado = subprocess.run(comando, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"  [ERROR WSL] SIENAX falló. STDERR: {resultado.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"  [FATAL] Error ejecutando comando WSL: {e}")
        return False


def extraer_metricas_sienax(dir_sienax: str) -> dict:
    """Lee el archivo report.sienax y extrae los volúmenes normalizados."""
    ruta_report = os.path.join(dir_sienax, "report.sienax")
    metricas = {}

    if not os.path.exists(ruta_report):
        print(f"  -> [ADVERTENCIA] No se encontró {ruta_report}")
        return metricas

    try:
        with open(ruta_report, 'r', encoding='utf-8') as f:
            for linea in f:
                if linea.startswith("VSCALING"):
                    metricas["v_scale"] = float(linea.split()[1])
                elif linea.startswith("GREY"):
                    metricas["materia_gris_normalizada"] = float(linea.split()[2])
                elif linea.startswith("WHITE"):
                    metricas["materia_blanca_normalizada"] = float(linea.split()[2])
                elif linea.startswith("BRAIN"):
                    metricas["volumen_cerebral_total_normalizado"] = float(linea.split()[2])
    except Exception as e:
        print(f"  -> [ERROR] Fallo al leer report.sienax: {e}")

    return metricas


def ejecutar_siena(ruta_basal: str, ruta_seguimiento: str, dir_salida: str, prefijo: str) -> bool:
    """Ejecuta FSL SIENA para medir la atrofia entre dos sesiones del mismo paciente."""
    print(f"  -> Ejecutando SIENA para {prefijo} (esto puede tardar varios minutos)...")

    dir_siena = os.path.join(dir_salida, f"{prefijo}_siena")
    basal_wsl = a_wsl(ruta_basal)
    seguimiento_wsl = a_wsl(ruta_seguimiento)
    dir_siena_wsl = a_wsl(dir_siena)

    comando_linux = (
        f"source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; "
        f"fsl5.0-siena {basal_wsl} {seguimiento_wsl} -o {dir_siena_wsl} "
        f"|| siena {basal_wsl} {seguimiento_wsl} -o {dir_siena_wsl}"
    )
    comando = ["wsl", "bash", "-c", comando_linux]

    try:
        resultado = subprocess.run(comando, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"  [ERROR WSL] SIENA falló. STDERR: {resultado.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"  [FATAL] Error ejecutando comando WSL: {e}")
        return False


def extraer_metricas_siena(dir_siena: str) -> dict:
    """
    Lee el informe de SIENA y extrae el PBVC (Porcentaje de Cambio de Volumen
    Cerebral). AVISO: el nombre exacto del archivo de reporte puede variar
    según tu versión de FSL (normalmente 'report', a veces 'report.siena') —
    verifícalo con `ls` en tu carpeta *_siena una vez tengas un caso real.
    """
    candidatos = ["report", "report.siena"]
    metricas = {}

    for nombre in candidatos:
        ruta_report = os.path.join(dir_siena, nombre)
        if os.path.exists(ruta_report):
            try:
                with open(ruta_report, 'r', encoding='utf-8') as f:
                    contenido = f.read()
                match = re.search(r"PBVC\s*=\s*(-?\d+\.?\d*)\s*%", contenido)
                if match:
                    metricas["pbvc_porcentaje"] = float(match.group(1))
                else:
                    print("  -> [ADVERTENCIA] No se encontró el valor PBVC en el report de SIENA.")
            except Exception as e:
                print(f"  -> [ERROR] Fallo al leer {nombre}: {e}")
            return metricas

    print(f"  -> [ADVERTENCIA] No se encontró ningún report de SIENA en {dir_siena}")
    return metricas


def buscar_imagenes_fsl(directorio: str) -> dict:
    """Busca las imágenes (png/gif) que SIENA/SIENAX dejan en su carpeta de salida."""
    imagenes = {}
    if not os.path.isdir(directorio):
        return imagenes
    for archivo in sorted(os.listdir(directorio)):
        if archivo.lower().endswith(('.png', '.gif')):
            imagenes[archivo] = os.path.join(directorio, archivo)
    return imagenes


# ============================================================
# FILTRO DE SECUENCIAS Y METADATOS
# ============================================================

def es_secuencia_t1(ruta_nifti: str) -> bool:
    """Lee el .json asociado (si existe) para asegurar que la secuencia es T1."""
    ruta_json = ruta_nifti.replace('.nii.gz', '.json')

    if not os.path.exists(ruta_json):
        return 't1' in os.path.basename(ruta_nifti).lower()

    try:
        with open(ruta_json, 'r', encoding='utf-8') as f:
            metadatos = json.load(f)

        descripcion = metadatos.get("SeriesDescription", "").lower()
        protocolo = metadatos.get("ProtocolName", "").lower()

        if 't2' in descripcion or 't2' in protocolo:
            return False
        if 'flair' in descripcion or 'flair' in protocolo:
            return False
        if 't1' in descripcion or 't1' in protocolo:
            return True

        return 't1' in os.path.basename(ruta_nifti).lower()

    except Exception as e:
        print(f"  [AVISO] No se pudo leer {os.path.basename(ruta_json)}: {e}")
        return 't1' in os.path.basename(ruta_nifti).lower()


def obtener_fecha_adquisicion(ruta_nifti: str, sesion: str) -> str:
    """Extrae la fecha del escáner desde el metadato BIDS o usa la sesión como proxy."""
    ruta_json = ruta_nifti.replace('.nii.gz', '.json')
    if os.path.exists(ruta_json):
        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                metadatos = json.load(f)
            fecha = metadatos.get("AcquisitionDate") or metadatos.get("AcquisitionDateTime")
            if fecha:
                return str(fecha)
        except Exception:
            pass

    return f"Desconocida (Orden lógico: {sesion})"


def parsear_bids(nombre_archivo: str) -> tuple:
    """Extrae (sujeto, sesion) de un nombre de archivo con convención BIDS."""
    partes = nombre_archivo.split('_')
    sujeto = next((p for p in partes if p.startswith('sub-')), 'sub-desconocido')
    sesion = next((p for p in partes if p.startswith('ses-')), 'ses-desconocida')
    return sujeto, sesion


# ============================================================
# MODO TRANSVERSAL (un paciente, un momento)
# ============================================================

def procesar_transversal(args, ruta_hdbet: str, output_dir: str) -> list:
    """Calcula resultados transversales (FAST + opcional SIENAX). No toca el JSON."""
    resultados = []

    if os.path.isfile(args.input) and args.input.endswith('.nii.gz'):
        if not es_secuencia_t1(args.input):
            print("[ERROR] El archivo no es una secuencia T1 válida.")
            return resultados
        input_dir = os.path.dirname(args.input)
        archivos_nifti = [os.path.basename(args.input)]
    elif os.path.isdir(args.input):
        input_dir = args.input
        archivos_nifti = [
            f for f in os.listdir(input_dir)
            if f.endswith('.nii.gz') and es_secuencia_t1(os.path.join(input_dir, f))
        ]
    else:
        print("[ERROR] La ruta de entrada no es una carpeta válida ni un archivo .nii.gz.")
        return resultados

    if not archivos_nifti:
        print("[AVISO] No se encontraron secuencias T1 válidas en la ruta proporcionada.")
        return resultados

    print(f"\nIniciando procesamiento transversal ({len(archivos_nifti)} archivo(s) T1 detectado(s))...\n")

    for archivo in archivos_nifti:
        print(f"Procesando resonancia: {archivo}")
        ruta_mri_original = os.path.join(input_dir, archivo)

        sujeto, sesion = parsear_bids(archivo)
        fecha_scan = obtener_fecha_adquisicion(ruta_mri_original, sesion)

        nombre_base = archivo.replace(".nii.gz", "")
        ruta_bet = os.path.join(output_dir, f"{nombre_base}_bet.nii.gz")
        prefijo_fast = nombre_base

        if not ejecutar_hdbet(ruta_hdbet, ruta_mri_original, ruta_bet):
            continue
        if not ejecutar_fsl_fast(ruta_bet, output_dir, prefijo_fast):
            continue

        ruta_csf = os.path.join(output_dir, f"{prefijo_fast}_pve_0.nii.gz")
        ruta_gm = os.path.join(output_dir, f"{prefijo_fast}_pve_1.nii.gz")
        ruta_wm = os.path.join(output_dir, f"{prefijo_fast}_pve_2.nii.gz")

        vol_lcr = calcular_volumen_tejido(ruta_csf)
        vol_gris = calcular_volumen_tejido(ruta_gm)
        vol_blanca = calcular_volumen_tejido(ruta_wm)
        vol_intracraneal = vol_lcr + vol_gris + vol_blanca

        metricas_sienax = {}
        imagenes_fsl = {}
        if args.sienax:
            if ejecutar_sienax(ruta_mri_original, output_dir, prefijo_fast):
                dir_sienax = os.path.join(output_dir, f"{prefijo_fast}_sienax")
                metricas_sienax = extraer_metricas_sienax(dir_sienax)
                imagenes_fsl = buscar_imagenes_fsl(dir_sienax)

        resultados.append({
            "tipo": "transversal",
            "paciente": sujeto,
            "sesion": sesion,
            "fecha": fecha_scan,
            "archivo_original": archivo,
            "volumenes_absolutos_mm3": {
                "materia_gris": vol_gris,
                "materia_blanca": vol_blanca,
                "liquido_cefalorraquideo": vol_lcr,
                "volumen_intracraneal_total": round(vol_intracraneal, 2),
            },
            "volumenes_sienax_normalizados": metricas_sienax,
            "imagenes_fsl": imagenes_fsl,
        })
        print("  -> ¡Completado!\n")

    return resultados


# ============================================================
# MODO LONGITUDINAL (mismo paciente, dos fechas -> SIENA)
# ============================================================

def procesar_longitudinal(args, output_dir: str) -> list:
    """Calcula el resultado longitudinal (SIENA). No toca el JSON."""
    ruta_basal = args.basal
    ruta_seguimiento = args.seguimiento

    for ruta in (ruta_basal, ruta_seguimiento):
        if not os.path.isfile(ruta):
            print(f"[ERROR] No se encontró el archivo: {ruta}")
            return []

    archivo_basal = os.path.basename(ruta_basal)
    archivo_seguimiento = os.path.basename(ruta_seguimiento)

    sujeto, sesion_basal = parsear_bids(archivo_basal)
    _, sesion_seguimiento = parsear_bids(archivo_seguimiento)

    print(f"\nIniciando análisis longitudinal (SIENA) para {sujeto}: "
          f"{sesion_basal} -> {sesion_seguimiento}\n")

    prefijo = f"{sujeto}_{sesion_basal}_vs_{sesion_seguimiento}"
    if not ejecutar_siena(ruta_basal, ruta_seguimiento, output_dir, prefijo):
        return []

    dir_siena = os.path.join(output_dir, f"{prefijo}_siena")
    metricas = extraer_metricas_siena(dir_siena)
    imagenes_fsl = buscar_imagenes_fsl(dir_siena)

    resultado = {
        "tipo": "longitudinal",
        "paciente": sujeto,
        "sesion_basal": sesion_basal,
        "sesion_seguimiento": sesion_seguimiento,
        "archivo_basal": archivo_basal,
        "archivo_seguimiento": archivo_seguimiento,
        "metricas": metricas,
        "imagenes_fsl": imagenes_fsl,
    }
    print("  -> ¡Completado!\n")
    return [resultado]


# ============================================================
# SALIDA: JSON acumulativo (base de datos)
# ============================================================

def cargar_o_crear_informe(ruta_informe: str) -> dict:
    if os.path.exists(ruta_informe):
        with open(ruta_informe, 'r', encoding='utf-8') as f:
            informe = json.load(f)
        informe["metadata"]["fecha_ultimo_registro"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return informe

    return {
        "metadata": {
            "fecha_creacion_bd": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "herramientas": "HD-BET + FSL FAST + SIENAX + SIENA (WSL)",
        },
        "pacientes": {},
    }


def _paciente(informe: dict, sujeto: str) -> dict:
    """Devuelve (creando si hace falta) la entrada del paciente, con sus dos sub-claves."""
    entrada = informe["pacientes"].setdefault(sujeto, {})
    entrada.setdefault("sesiones", {})
    entrada.setdefault("comparaciones_longitudinales", {})
    return entrada


def fusionar_resultado(informe: dict, resultado: dict):
    """Mezcla un resultado (transversal o longitudinal) en la base de datos acumulativa."""
    entrada = _paciente(informe, resultado["paciente"])

    if resultado["tipo"] == "transversal":
        entrada["sesiones"][resultado["sesion"]] = {
            "fecha_adquisicion": resultado["fecha"],
            "archivo_original": resultado["archivo_original"],
            "volumenes_absolutos_mm3": resultado["volumenes_absolutos_mm3"],
            "volumenes_sienax_normalizados": resultado["volumenes_sienax_normalizados"],
        }
    else:  # longitudinal
        clave = f"{resultado['sesion_basal']}_vs_{resultado['sesion_seguimiento']}"
        entrada["comparaciones_longitudinales"][clave] = {
            "archivo_basal": resultado["archivo_basal"],
            "archivo_seguimiento": resultado["archivo_seguimiento"],
            "pbvc_porcentaje": resultado["metricas"].get("pbvc_porcentaje"),
        }


def guardar_json(informe: dict, ruta_salida: str):
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=4, ensure_ascii=False)


# ============================================================
# SALIDA: HTML del informe de ESTA ejecución (no recalcula nada)
# ============================================================

def _imagen_a_base64(ruta_imagen: str) -> str:
    """Incrusta la imagen en el HTML para que el archivo sea autocontenido."""
    if not ruta_imagen or not os.path.exists(ruta_imagen):
        return ""
    with open(ruta_imagen, "rb") as f:
        datos = base64.b64encode(f.read()).decode("utf-8")
    extension = os.path.splitext(ruta_imagen)[1].lstrip('.').lower() or "png"
    return f"data:image/{extension};base64,{datos}"


import os
import json
from datetime import datetime

def generar_html(resultados, ruta_informe_html):
    """
    Genera un informe HTML estructurado, visual y autocontenido a partir de los resultados volumétricos.
    """
    html_content = f"""<!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Reporte Clínico MedVision</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
            h2 {{ color: #2980b9; margin-top: 30px; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
            
            .header-info {{ background: #ecf0f1; padding: 15px; border-radius: 6px; margin-bottom: 20px; display: flex; justify-content: space-between; flex-wrap: wrap; border-left: 5px solid #3498db; }}
            .header-info div {{ margin: 5px 15px 5px 0; }}
            .header-info p {{ margin: 5px 0; font-weight: bold; }}
            .header-info span {{ font-weight: normal; }}
            
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 30px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #34495e; color: white; }}
            tr:hover {{ background-color: #f5f5f5; }}
            
            .qa-section {{ margin-top: 40px; }}
            .qa-card {{ display: flex; flex-direction: column; background: #fafafa; border: 1px solid #e0e0e0; border-radius: 6px; margin-bottom: 25px; overflow: hidden; }}
            .qa-header {{ background: #2c3e50; color: white; padding: 10px 15px; margin: 0; font-size: 16px; }}
            .qa-body {{ padding: 15px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
            .qa-description {{ flex: 1; min-width: 250px; font-size: 14px; color: #555; line-height: 1.5; }}
            .qa-image {{ max-width: 65%; border-radius: 4px; border: 1px solid #ccc; }}
            .qa-image-full {{ max-width: 100%; border-radius: 4px; border: 1px solid #ccc; margin-top: 10px; }}
            
            .credits-section {{ margin-top: 40px; padding-top: 20px; border-top: 2px solid #ecf0f1; font-size: 12px; color: #7f8c8d; line-height: 1.6; }}
            .credits-section h3 {{ color: #34495e; font-size: 14px; margin-bottom: 10px; }}
            .references {{ padding-left: 15px; margin-bottom: 15px; }}
            .references li {{ margin-bottom: 6px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Informe Volumétrico MedVision</h1>
    """

    for res in resultados:
        paciente = res.get("paciente", "Desconocido")
        sesion = res.get("sesion", "Desconocida")
        tipo = res.get("tipo", "transversal")
        archivo_orig = res.get("archivo_original", "N/A")
        v_abs = res.get("volumenes_absolutos_mm3", {})
        v_norm = res.get("volumenes_sienax_normalizados", {})
        imgs = res.get("imagenes_fsl", {})

        html_content += f"""
            <div class="header-info">
                <div>
                    <p>Paciente: <span>{paciente}</span></p>
                    <p>Sesión: <span>{sesion}</span></p>
                </div>
                <div>
                    <p>Modalidad: <span>{tipo.capitalize()}</span></p>
                    <p>Archivo: <span>{archivo_orig}</span></p>
                </div>
                <div>
                    <p>Fecha Reporte: <span>{datetime.now().strftime('%Y-%m-%d %H:%M')}</span></p>
                </div>
            </div>

            <h2>Cuantificación Tisular</h2>
            <table>
                <tr>
                    <th>Tejido Anatómico</th>
                    <th>Volumen Absoluto (mm³)</th>
                    <th>Volumen Normalizado (mm³) *</th>
                </tr>
                <tr>
                    <td>Materia Gris (GM)</td>
                    <td>{v_abs.get("materia_gris", "N/A")}</td>
                    <td>{v_norm.get("materia_gris_normalizada", "N/A") if v_norm else "N/A"}</td>
                </tr>
                <tr>
                    <td>Materia Blanca (WM)</td>
                    <td>{v_abs.get("materia_blanca", "N/A")}</td>
                    <td>{v_norm.get("materia_blanca_normalizada", "N/A") if v_norm else "N/A"}</td>
                </tr>
                <tr>
                    <td>Líquido Cefalorraquídeo (CSF)</td>
                    <td>{v_abs.get("liquido_cefalorraquideo", "N/A")}</td>
                    <td>N/A</td>
                </tr>
                <tr style="font-weight: bold; background-color: #e8f4f8;">
                    <td>Volumen Cerebral Total (TBV)</td>
                    <td>{v_abs.get("volumen_intracraneal_total", "N/A")}</td>
                    <td>{v_norm.get("volumen_cerebral_total_normalizado", "N/A") if v_norm else "N/A"}</td>
                </tr>
            </table>
        """
        
        if v_norm:
            v_scale = v_norm.get("v_scale", "N/A")
            html_content += f"""
            <p style="font-size: 12px; color: #7f8c8d; margin-top: -20px; margin-bottom: 30px;">
                * La normalización se estima multiplicando el volumen absoluto por el Factor de Escala de SIENAX (v_scale: {v_scale}).
            </p>
            """

        html_content += """
            <div class="qa-section">
                <h2>Control de Calidad (QA) FSL</h2>
        """
        
        descripciones_qa = {
            "I_bet.png": (
                "Extracción Craneal (HD-BET / Skull-Stripping)", 
                "Muestra el parénquima cerebral aislado superpuesto sobre la resonancia magnética original. Permite al especialista verificar visualmente que el algoritmo no ha recortado tejido cortical válido ni ha incluido duramadre, cráneo o globos oculares.", 
                "qa-image"
            ),
            "I2std.png": (
                "Registro al Espacio Estándar (FLIRT MNI152)", 
                "Verifica la alineación afín del cerebro del paciente (imagen de fondo) contra el atlas anatómico estándar MNI152 (bordes rojos). Este registro geométrico es el paso crítico que permite a SIENAX calcular el 'v_scale' (factor de normalización) para corregir el tamaño de la cabeza del paciente.", 
                "qa-image"
            ),
            "I_masks.png": (
                "Máscara de Cobertura (Field of View)", 
                "Asegura que el cerebro extraído (azul) y la máscara del espacio estándar (líneas rojas) intersecan correctamente (zona verde). Garantiza que ninguna parte del encéfalo ha quedado fuera del campo de visión (FOV) del escáner durante el procesamiento.", 
                "qa-image"
            ),
            "I_render.png": (
                "Segmentación Final de Tejidos (FAST)", 
                "Renderizado multicorte que visualiza la clasificación probabilística final de los vóxeles. Permite auditar la separación de los tejidos: Materia Gris, Materia Blanca y Líquido Cefalorraquídeo en los planos axiales, sagitales y coronales.", 
                "qa-image-full"
            )
        }

        for img_name, info in descripciones_qa.items():
            if img_name in imgs:
                titulo, descripcion, img_class = info
                img_data = imgs[img_name]
                
                style_body = ' style="flex-direction: column; align-items: flex-start;"' if img_class == "qa-image-full" else ''
                
                html_content += f"""
                <div class="qa-card">
                    <h3 class="qa-header">{titulo}</h3>
                    <div class="qa-body"{style_body}>
                        <p class="qa-description">{descripcion}</p>
                        <img class="{img_class}" src="{img_data}" alt="{titulo}">
                    </div>
                </div>
                """

        html_content += "<hr style='border:1px solid #ecf0f1; margin: 40px 0;'>"

    html_content += """
            </div>

            <!-- SECCIÓN DE CRÉDITOS Y METODOLOGÍA -->
            <div class="credits-section">
                <h3>Metodología Científica</h3>
                <p>El volumen del tejido cerebral, normalizado por el tamaño de la cabeza del sujeto, se estimó con la herramienta SIENAX, parte de la librería FSL. La extracción primaria del cerebro se delegó a la red neuronal artificial HD-BET para una mayor precisión. Posteriormente, la imagen se registró de forma afín al espacio estándar MNI152 para obtener el factor de escala volumétrico (V-scale), utilizado como normalización del tamaño craneal. Finalmente, la segmentación de tipos de tejido con estimación de volumen parcial se llevó a cabo mediante el algoritmo FAST.</p>
                
                <h3>Referencias</h3>
                <ul class="references">
                    <li><em>Smith, S.M., et al. (2002). Accurate, robust and automated longitudinal and cross-sectional brain change analysis. NeuroImage, 17(1):479-489.</em></li>
                    <li><em>Isensee, F., et al. (2019). Automated brain extraction of multisequence MRI using artificial neural networks. Human Brain Mapping, 40(17):4952-4964. (HD-BET)</em></li>
                    <li><em>Zhang, Y., et al. (2001). Segmentation of brain MR images through a hidden Markov random field model and the expectation maximization algorithm. IEEE Trans. on Medical Imaging, 20(1):45-57.</em></li>
                </ul>

                <h3>Desarrollo</h3>
                <p>Pipeline <strong>MedVision</strong> y generador de reportes HTML desarrollados por <strong>Miriam Rodríguez García</strong>.</p>
            </div>
        </div>
    </body>
    </html>
    """

    with open(ruta_informe_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
# ============================================================
# CLI
# ============================================================

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
    # Añadimos dest="basal" y dest="seguimiento" para que el código interno no se rompa
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

    if args.modo == "t":
        resultados = procesar_transversal(args, ruta_hdbet, output_dir)
    else:
        resultados = procesar_longitudinal(args, output_dir)

    if not resultados:
        print("No se generaron resultados en esta ejecución.")
        return

    # --- Salida 1: JSON acumulativo (base de datos histórica) ---
    ruta_informe_json = os.path.join(output_dir, "informe_volumetrico_medvision.json")
    informe = cargar_o_crear_informe(ruta_informe_json)
    for resultado in resultados:
        fusionar_resultado(informe, resultado)
    guardar_json(informe, ruta_informe_json)

    # --- Salida 2: HTML de esta ejecución (reaprovecha imágenes FSL) ---
    ruta_informe_html = os.path.join(
        output_dir, f"informe_{args.modo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    )
    generar_html(resultados, ruta_informe_html)

    print("=== PROCESO FINALIZADO ===")
    print(f"JSON actualizado: {ruta_informe_json}")
    print(f"HTML generado:    {ruta_informe_html}")


if __name__ == "__main__":
    main()