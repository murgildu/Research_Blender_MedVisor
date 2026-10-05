import os
import re
import subprocess
import nibabel as nib
import numpy as np

# Importaciones del módulo de utilidades propio
from utils import (
    a_wsl, es_secuencia_t1, obtener_fecha_adquisicion, 
    parsear_bids, limpiar_archivos_temporales, buscar_imagenes_fsl
)

def ejecutar_hdbet(ruta_hdbet: str, entrada: str, salida: str) -> bool:
    print("  -> Ejecutando HD-BET...")
    comando = [ruta_hdbet, "-i", entrada, "-o", salida]
    try:
        subprocess.run(comando, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError:
        print("  [ERROR] Falló la ejecución de HD-BET.")
        return False

def ejecutar_fsl_fast(ruta_entrada: str, directorio_salida: str, prefijo: str) -> bool:
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

def ejecutar_sienax(ruta_mri_original: str, dir_salida: str, prefijo: str) -> bool:
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

def procesar_transversal(args, ruta_hdbet: str, output_dir: str) -> list:
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
        limpiar_archivos_temporales(output_dir, nombre_base)

    return resultados

def procesar_longitudinal(args, output_dir: str) -> list:
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

    print(f"\nIniciando análisis longitudinal (SIENA) para {sujeto}: {sesion_basal} -> {sesion_seguimiento}\n")

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