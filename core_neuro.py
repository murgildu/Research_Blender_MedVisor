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
        f"fsl5.0-fast -t 1 -n 3 -p -o \"{ruta_base_salida_wsl}\" \"{ruta_entrada_wsl}\" "
        f"|| fast -t 1 -n 3 -p -o \"{ruta_base_salida_wsl}\" \"{ruta_entrada_wsl}\""
    )
    comando = ["wsl", "bash", "-lc", comando_linux]
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
        f"fsl5.0-sienax \"{ruta_mri_wsl}\" -o \"{dir_sienax_wsl}\" "
        f"|| sienax \"{ruta_mri_wsl}\" -o \"{dir_sienax_wsl}\""
    )
    comando = ["wsl", "bash", "-lc", comando_linux]
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
                p = linea.split()
                if linea.startswith("VSCALING"):
                    metricas["v_scale"] = float(p[1])
                elif linea.startswith("GREY"):
                    metricas["materia_gris_normalizada"] = float(p[1])
                    metricas["materia_gris_sin_normalizar"] = float(p[2])
                elif linea.startswith("WHITE"):
                    metricas["materia_blanca_normalizada"] = float(p[1])
                    metricas["materia_blanca_sin_normalizar"] = float(p[2])
                elif linea.startswith("BRAIN"):
                    metricas["volumen_cerebral_total_normalizado"] = float(p[1])
                    metricas["volumen_cerebral_total_sin_normalizar"] = float(p[2])
                    
        if all(k in metricas for k in ("v_scale", "volumen_cerebral_total_normalizado", "volumen_cerebral_total_sin_normalizar")):
            esperado = metricas["volumen_cerebral_total_sin_normalizar"] * metricas["v_scale"]
            if abs(esperado - metricas["volumen_cerebral_total_normalizado"]) / esperado > 0.01:
                print("  [ADVERTENCIA] normalizado != sin_normalizar × VSCALING; revisa report.sienax")
                
    except Exception as e:
        print(f"  -> [ERROR] Fallo al leer report.sienax: {e}")
    return metricas

def ejecutar_siena(ruta_basal: str, ruta_seguimiento: str, dir_salida: str, prefijo: str, opciones: str = "") -> bool:
    dir_siena = os.path.join(dir_salida, f"{prefijo}_siena")
    
    # --- BLOQUEO DE CONTAMINACIÓN ---
    if os.path.exists(dir_siena):
        print(f"  [ERROR] {dir_siena} ya existe; SIENA podría reutilizar resultados anteriores. Bórrala o usa otra carpeta de salida.")
        return False
    # --------------------------------

    print(f"  -> Ejecutando SIENA para {prefijo} (esto puede tardar varios minutos)...")
    basal_wsl = a_wsl(ruta_basal)
    seguimiento_wsl = a_wsl(ruta_seguimiento)
    dir_siena_wsl = a_wsl(dir_siena)
    comando_linux = (
        f"source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; "
        f"fsl5.0-siena \"{basal_wsl}\" \"{seguimiento_wsl}\" -o \"{dir_siena_wsl}\" {opciones} "
        f"|| siena \"{basal_wsl}\" \"{seguimiento_wsl}\" -o \"{dir_siena_wsl}\" {opciones}"
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
    metricas = {}
    report_path = os.path.join(dir_siena, "report.siena")
    
    if not os.path.exists(report_path):
        return metricas

    with open(report_path, "r") as f:
        contenido = f.read()

    # Extraer PBVC final
    final = re.search(r"finalPBVC\s+(-?\d+(?:\.\d+)?)", contenido)
    if final:
        metricas["pbvc_porcentaje"] = float(final.group(1))

    # Extraer las dos mitades del registro tal cual
    mitades = re.findall(r"^PBVC\s+(-?\d+(?:\.\d+)?)", contenido, flags=re.M)
    if len(mitades) == 2:
        metricas["pbvc_extremos"] = [float(x) for x in mitades]

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
        nombre_base = archivo.replace(".nii.gz", "")
        if sujeto == 'sub-desconocido': 
            sujeto = nombre_base

        fecha_scan = obtener_fecha_adquisicion(ruta_mri_original, sesion)
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
                "cerebro_total": round(vol_gris + vol_blanca, 2),
                "volumen_tejido_mascara_hdbet": round(vol_intracraneal, 2),
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

    # 1. Validación de archivos y modalidad
    for ruta in (ruta_basal, ruta_seguimiento):
        if not os.path.isfile(ruta):
            print(f"[ERROR] No se encontró el archivo: {ruta}")
            return []
        if not es_secuencia_t1(ruta):
            print(f"[ERROR] {os.path.basename(ruta)} no parece ser T1. SIENA exige exactamente la misma modalidad en ambas.")
            return []

    archivo_basal = os.path.basename(ruta_basal)
    archivo_seguimiento = os.path.basename(ruta_seguimiento)
    
    # 2. Parseo BIDS tolerante a formatos complejos (como ADNI)
    sujeto, sesion_basal = parsear_bids(archivo_basal)
    sujeto_b, sesion_seguimiento = parsear_bids(archivo_seguimiento)

    # 3. Reglas de control (El "portero" permite la misma sesión para validar A vs A)
    if sujeto != sujeto_b or sujeto == 'sub-desconocido':
        print(f"[ERROR] No se identifican sujeto/sesiones. Usa BIDS estricto (ej: sub-002_S_0619_ses-2006_T1w.nii.gz).")
        return []
        
    if sesion_basal > sesion_seguimiento:
        print("[AVISO] --a debería ser anterior a --r; de lo contrario el signo del PBVC se invertirá.")

    # 4. Opciones adicionales para SIENA (ej: correcciones de BET)
    opciones_siena = getattr(args, 'siena_opts', '')

    print(f"\nIniciando análisis longitudinal (SIENA) para {sujeto}: {sesion_basal} -> {sesion_seguimiento}\n")

    prefijo = f"{sujeto}_{sesion_basal}_vs_{sesion_seguimiento}"
    
    # IMPORTANTE: Asegúrate de que tu función ejecutar_siena acepte 'opciones_siena' como 5º parámetro
    if not ejecutar_siena(ruta_basal, ruta_seguimiento, output_dir, prefijo, opciones_siena):
        return []

    # 5. Extracción de resultados
    dir_siena = os.path.join(output_dir, f"{prefijo}_siena")
    metricas = extraer_metricas_siena(dir_siena)
    imagenes_fsl = buscar_imagenes_fsl(dir_siena)

    # 6. Cálculo del PBVC anualizado
    pbvc = metricas.get("pbvc_porcentaje", 0.0)
    try:
        # Intenta extraer los años del string de la sesión (ej: "ses-2006" -> 2006)
        anio_a = int(''.join(filter(str.isdigit, sesion_basal)))
        anio_b = int(''.join(filter(str.isdigit, sesion_seguimiento)))
        anios_transcurridos = abs(anio_b - anio_a)
        
        # Evitar división por cero en la prueba A vs A
        if anios_transcurridos == 0: 
            anios_transcurridos = 1 
            
        metricas["pbvc_anualizado"] = round(pbvc / anios_transcurridos, 6)
    except Exception:
        # Fallback en caso de que las sesiones no contengan años explícitos (aplica la media de 804 días / 2.2 años)
        metricas["pbvc_anualizado"] = round(pbvc / 2.2, 6)

    resultado = {
        "tipo": "longitudinal",
        "paciente": sujeto,
        "sesion_basal": sesion_basal,
        "sesion_seguimiento": sesion_seguimiento,
        "archivo_basal": archivo_basal,
        "archivo_seguimiento": archivo_seguimiento,
        "siena_opts": opciones_siena,  # Nueva línea
        "metricas": metricas,
        "imagenes_fsl": imagenes_fsl,
    }
    
    print("  -> ¡Completado!\n")
    return [resultado]