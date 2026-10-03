import os
import json
import subprocess
import argparse
import configparser
from datetime import datetime
import nibabel as nib
import numpy as np

def cargar_configuracion(ruta_config="config.ini"):
    """Lee el archivo de configuración con las rutas del sistema."""
    config = configparser.ConfigParser()
    if os.path.exists(ruta_config):
        config.read(ruta_config)
        return config
    return None

def ejecutar_hdbet(ruta_hdbet: str, entrada: str, salida: str) -> bool:
    """Ejecuta HD-BET para la extracción del cráneo."""
    print(f"  -> Ejecutando HD-BET...")
    comando = [ruta_hdbet, "-i", entrada, "-o", salida]
    try:
        subprocess.run(comando, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        return True
    except subprocess.CalledProcessError:
        print("  [ERROR] Falló la ejecución de HD-BET.")
        return False

def ejecutar_fsl_fast(ruta_entrada: str, directorio_salida: str, prefijo: str) -> bool:
    """Ejecuta FSL FAST a través de WSL forzando el PATH de Linux."""
    print(f"  -> Ejecutando FSL FAST (Segmentación PVE)...")
    
    # Traductor de rutas Windows -> WSL
    def a_wsl(ruta_win):
        ruta = ruta_win.replace('\\', '/')
        if ':' in ruta:
            letra, resto = ruta.split(':', 1)
            return f"/mnt/{letra.lower()}{resto}"
        return ruta

    ruta_entrada_wsl = a_wsl(ruta_entrada)
    ruta_base_salida_wsl = a_wsl(os.path.join(directorio_salida, prefijo))
    
    # Forzamos la carga del perfil bash de Ubuntu para encontrar FSL
    comando_linux = f"source ~/.bashrc 2>/dev/null; source ~/.profile 2>/dev/null; fsl5.0-fast -t 1 -n 3 -p -o {ruta_base_salida_wsl} {ruta_entrada_wsl} || fast -t 1 -n 3 -p -o {ruta_base_salida_wsl} {ruta_entrada_wsl}"
    comando = ["wsl", "bash", "-c", comando_linux]
    
    try:
        resultado = subprocess.run(comando, capture_output=True, text=True)
        if resultado.returncode != 0:
            print(f"  [ERROR WSL] Mensaje desde Linux:\n  STDERR: {resultado.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"  [FATAL] Error ejecutando comando WSL: {e}")
        return False

def calcular_volumen_tejido(ruta_imagen: str) -> float:
    """Calcula el volumen en mm3 a partir de un archivo NIfTI de probabilidad."""
    if not os.path.exists(ruta_imagen):
        return 0.0
    try:
        img = nib.load(ruta_imagen)
        datos = img.get_fdata()
        voxel_dims = img.header.get_zooms()
        vol_voxel = voxel_dims[0] * voxel_dims[1] * voxel_dims[2]
        # Sumamos la probabilidad de todos los vóxeles y multiplicamos por el volumen del vóxel
        vol_total = np.sum(datos) * vol_voxel
        return round(vol_total, 2)
    except Exception as e:
        print(f"  [ERROR] Falló el cálculo de volumen: {e}")
        return 0.0

def es_secuencia_t1(ruta_nifti: str) -> bool:
    """Lee el .json asociado (si existe) para asegurar que la secuencia es T1."""
    ruta_json = ruta_nifti.replace('.nii.gz', '.json')
    
    if not os.path.exists(ruta_json):
        # Fallback: Si no hay JSON clínico, nos fiamos del nombre del archivo
        return 't1' in os.path.basename(ruta_nifti).lower()
        
    try:
        with open(ruta_json, 'r', encoding='utf-8') as f:
            metadatos = json.load(f)
            
        # Extraemos los campos DICOM/BIDS más comunes
        descripcion = metadatos.get("SeriesDescription", "").lower()
        protocolo = metadatos.get("ProtocolName", "").lower()
        
        # Rechazo explícito de modalidades que arruinarían la segmentación
        if 't2' in descripcion or 't2' in protocolo: return False
        if 'flair' in descripcion or 'flair' in protocolo: return False
        
        # Aceptación explícita
        if 't1' in descripcion or 't1' in protocolo: return True
        
        # Fallback final si los metadatos no son claros
        return 't1' in os.path.basename(ruta_nifti).lower()
        
    except Exception as e:
        print(f"  [AVISO] No se pudo leer {os.path.basename(ruta_json)}: {e}")
        return 't1' in os.path.basename(ruta_nifti).lower()

def main():
    print("==================================================")
    print("      MedVision - Análisis Volumétrico CLI        ")
    print("==================================================\n")
    
    # 1. Configurar CLI con argparse
    parser = argparse.ArgumentParser(description="MedVision Headless: Orquestador de segmentación MRI.")
    parser.add_argument("-i", "--input", required=True, help="Ruta del archivo o carpeta de entrada (.nii.gz)")
    parser.add_argument("-o", "--output", required=True, help="Ruta de la carpeta para guardar el informe")
    parser.add_argument("-c", "--config", default="config.ini", help="Ruta al archivo de configuración config.ini")
    
    args = parser.parse_args()
    
    # 2. Asignar rutas desde argumentos
    input_dir = args.input
    output_dir = args.output
    
    # 3. Leer variables de entorno/configuración
    config = cargar_configuracion(args.config)
    if not config or 'RUTAS' not in config:
        print(f"\n[ERROR] No se encontró el archivo {args.config} o falta la sección [RUTAS].")
        return
        
    ruta_hdbet = config['RUTAS'].get('hdbet')

    # Detectar si es un archivo directo o una carpeta y aplicar el filtro inteligente
    archivos_nifti = []
    if os.path.isfile(input_dir) and input_dir.endswith('.nii.gz'):
        if es_secuencia_t1(input_dir):
            archivos_nifti = [os.path.basename(input_dir)]
            input_dir = os.path.dirname(input_dir)
        else:
            print(f"\n[ERROR] El archivo {os.path.basename(input_dir)} no es una secuencia T1 válida.")
            return
            
    elif os.path.isdir(input_dir):
        candidatos = [f for f in os.listdir(input_dir) if f.endswith('.nii.gz')]
        for archivo in candidatos:
            ruta_completa = os.path.join(input_dir, archivo)
            if es_secuencia_t1(ruta_completa):
                archivos_nifti.append(archivo)
            else:
                print(f"[FILTRO] Descartando {archivo} (Secuencia incompatible)")
    else:
        print("\n[ERROR] La ruta no es una carpeta válida ni un archivo .nii.gz.")
        return

    if not archivos_nifti:
        print("\n[AVISO] No se encontraron secuencias T1 válidas en la ruta proporcionada.")
        return

    os.makedirs(output_dir, exist_ok=True)
    ruta_informe = os.path.join(output_dir, "informe_volumetrico_medvision.json")
    
    # Lógica de Base de Datos Acumulativa
    if os.path.exists(ruta_informe):
        with open(ruta_informe, 'r', encoding='utf-8') as f:
            informe_paciente = json.load(f)
        # Actualizamos la fecha de la base de datos
        informe_paciente["metadata"]["fecha_ultimo_registro"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        informe_paciente = {
            "metadata": {
                "fecha_creacion_bd": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "herramientas": "HD-BET + FSL FAST (WSL)"
            },
            "resonancias": {}
        }

    print(f"\nIniciando procesamiento en lote ({len(archivos_nifti)} archivos detectados)...\n")
    
    for archivo in archivos_nifti:
        print(f"Procesando resonancia: {archivo}")
        ruta_mri_original = os.path.join(input_dir, archivo)
        
        nombre_base = archivo.replace(".nii.gz", "")
        ruta_bet = os.path.join(output_dir, f"{nombre_base}_bet.nii.gz")
        prefijo_fast = nombre_base
        
        # 1. Pipeline de ejecución
        exito_bet = ejecutar_hdbet(ruta_hdbet, ruta_mri_original, ruta_bet)
        if not exito_bet: continue
            
        exito_fast = ejecutar_fsl_fast(ruta_bet, output_dir, prefijo_fast)
        if not exito_fast: continue
        
        ruta_csf = os.path.join(output_dir, f"{prefijo_fast}_pve_0.nii.gz")
        ruta_gm = os.path.join(output_dir, f"{prefijo_fast}_pve_1.nii.gz")
        ruta_wm = os.path.join(output_dir, f"{prefijo_fast}_pve_2.nii.gz")
        
        # 2. Extracción de métricas
        vol_lcr = calcular_volumen_tejido(ruta_csf)
        vol_gris = calcular_volumen_tejido(ruta_gm)
        vol_blanca = calcular_volumen_tejido(ruta_wm)
        vol_intracraneal = vol_lcr + vol_gris + vol_blanca
        
        # 3. Guardar en estructura de datos
        informe_paciente["resonancias"][archivo] = {
            "volumenes_mm3": {
                "materia_gris": vol_gris,
                "materia_blanca": vol_blanca,
                "liquido_cefalorraquideo": vol_lcr,
                "volumen_intracraneal_total": round(vol_intracraneal, 2)
            }
        }
        print("  -> ¡Completado y registrado!\n")

    # 4. Volcado final a JSON
    with open(ruta_informe, 'w', encoding='utf-8') as f:
        json.dump(informe_paciente, f, indent=4, ensure_ascii=False)
        
    print(f"=== PROCESO FINALIZADO ===")
    print(f"Informe JSON generado correctamente en: {ruta_informe}")

if __name__ == "__main__":
    main()