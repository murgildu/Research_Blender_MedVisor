import os
import json
import shutil
import glob

def a_wsl(ruta_win: str) -> str:
    """Convierte una ruta de Windows (D:\\...) a su equivalente en WSL (/mnt/d/...)."""
    ruta = ruta_win.replace('\\', '/')
    if ':' in ruta:
        letra, resto = ruta.split(':', 1)
        return f"/mnt/{letra.lower()}{resto}"
    return ruta

def buscar_imagenes_fsl(directorio: str) -> dict:
    """Busca las imágenes (png/gif) que SIENA/SIENAX dejan en su carpeta de salida."""
    imagenes = {}
    if not os.path.isdir(directorio):
        return imagenes
    for archivo in sorted(os.listdir(directorio)):
        if archivo.lower().endswith(('.png', '.gif')):
            imagenes[archivo] = os.path.join(directorio, archivo)
    return imagenes

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

def limpiar_archivos_temporales(directorio_salida, nombre_archivo_base):
    """
    Limpia los archivos intermedios generados por FSL FAST y HD-BET.
    Elimina los cálculos matemáticos residuales y organiza los volúmenes 3D útiles.
    """
    print(f"  -> Limpiando archivos temporales de {nombre_archivo_base}...")
    
    carpeta_paciente = os.path.join(directorio_salida, f"{nombre_archivo_base}_sienax")
    
    if not os.path.exists(carpeta_paciente):
        os.makedirs(carpeta_paciente, exist_ok=True)
    
    patrones_eliminar = [
        f"{nombre_archivo_base}_mixeltype.nii.gz",
        f"{nombre_archivo_base}_prob_*.nii.gz",
        f"{nombre_archivo_base}_pve_*.nii.gz",
        f"{nombre_archivo_base}_seg.nii.gz"
    ]
    
    archivos_mover = [
        f"{nombre_archivo_base}_bet.nii.gz",
        f"{nombre_archivo_base}_pveseg.nii.gz"
    ]

    for patron in patrones_eliminar:
        for archivo in glob.glob(os.path.join(directorio_salida, patron)):
            try:
                os.remove(archivo)
            except Exception as e:
                print(f"     [Aviso] No se pudo eliminar {archivo}: {e}")

    for archivo_nombre in archivos_mover:
        ruta_origen = os.path.join(directorio_salida, archivo_nombre)
        ruta_destino = os.path.join(carpeta_paciente, archivo_nombre)
        if os.path.exists(ruta_origen):
            try:
                shutil.move(ruta_origen, ruta_destino)
            except Exception as e:
                print(f"     [Aviso] No se pudo mover {archivo_nombre}: {e}")